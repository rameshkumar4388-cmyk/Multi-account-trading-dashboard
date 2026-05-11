"""
Standalone VPS debug trace — no Streamlit required.

Run on the VPS:
    cd /path/to/dashboard
    python debug_trace.py

Prints the complete data pipeline at every layer and highlights
discrepancies between the Zerodha API response and the final computed values.
"""
import sys, os, inspect, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEP = "─" * 72


def hr(title=""):
    if title:
        print(f"\n{SEP}\n  {title}\n{SEP}")
    else:
        print(SEP)


def fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


# ── Bootstrap ─────────────────────────────────────────────────────────
hr("BOOTSTRAP")
from config.settings import load_settings
settings = load_settings()
print(f"APP_MODE      : {settings.app_mode}")
print(f"Accounts      : {[a.account_id for a in settings.accounts]}")

from database.db import Database
db = Database(settings.db_path)

from services.account_service import AccountService
account_svc = AccountService(settings, db=db)
account_svc.initialize()

active_ids = account_svc.list_account_ids()
print(f"Active accounts: {active_ids}")
if not active_ids:
    print("ERROR: No active accounts. Check credentials and run with APP_MODE=live.")
    sys.exit(1)

# ── Module identity ───────────────────────────────────────────────────
hr("MODULE IDENTITY (stale-cache check)")
from schemas.holding import Holding
from schemas.account import AccountSummary, MarginInfo
from brokers.zerodha.adapter import ZerodhaAdapter

for label, obj in [
    ("Holding",        Holding),
    ("AccountSummary", AccountSummary),
    ("ZerodhaAdapter", ZerodhaAdapter),
]:
    try:
        path = inspect.getfile(obj)
    except Exception as e:
        path = f"ERROR: {e}"
    print(f"  {label:<20} {path}")

# ── Per-account trace ─────────────────────────────────────────────────
for account_id in active_ids:
    hr(f"ACCOUNT: {account_id}")
    health = account_svc.get_health().get(account_id)
    print(f"  Status : {health.status if health else 'unknown'}")
    print(f"  AuthAt : {health.authenticated_at if health else '—'}")

    adapter = account_svc.get_adapter(account_id)
    print(f"  Adapter: {type(adapter).__name__}")

    # ── Layer 1: Raw Zerodha API ──────────────────────────────────────
    kite_sessions = account_svc.get_kite_sessions()
    kite = kite_sessions.get(account_id)

    if kite is None and hasattr(adapter, "_sessions"):
        kite = adapter._sessions.get(account_id)

    if kite is not None:
        print("\n  [Layer 1] Raw kite.holdings() response")
        try:
            t0 = time.monotonic()
            raw_holdings = kite.holdings()
            ms = (time.monotonic() - t0) * 1000
            print(f"  API returned {len(raw_holdings)} rows in {ms:.0f} ms")
            for r in raw_holdings[:5]:
                sym    = r.get("tradingsymbol", "?")
                qty    = r.get("quantity", "?")
                t1     = r.get("t1_quantity", "?")
                auth   = r.get("authorised_quantity", "?")   # pledge pending CDSL OTP
                collat = r.get("collateral_quantity", "?")   # pledge approved (v3 canonical)
                used   = r.get("used_quantity", "?")         # legacy/margin-in-use field
                opn    = r.get("opening_quantity", "?")      # session-open balance
                lp     = r.get("last_price", "?")
                avg    = r.get("average_price", "?")
                pnl    = r.get("pnl", "?")
                try:
                    _col   = int(collat or 0)
                    _used  = int(used   or 0)
                    total  = (int(qty  or 0) + int(t1   or 0)
                              + int(auth or 0) + max(_col, _used))
                    if total == 0:
                        total = int(opn or 0)  # opening_quantity fallback
                except Exception:
                    total = "?"
                print(
                    f"    {sym:<20} qty={qty} t1={t1} auth={auth} "
                    f"collat={collat} used={used} open={opn} "
                    f"TOTAL={total}  lp={lp}  avg={avg}  pnl={pnl}"
                )
            if len(raw_holdings) > 5:
                print(f"    ... ({len(raw_holdings) - 5} more)")
        except Exception as e:
            print(f"  kite.holdings() FAILED: {e}")

        print("\n  [Layer 1] Raw kite.margins() response")
        try:
            funds = kite.margins()
            eq    = funds.get("equity", {})
            av    = eq.get("available", {})
            ut    = eq.get("utilised", {})
            print(f"    cash         = {av.get('cash')}")
            print(f"    collateral   = {av.get('collateral')}")
            print(f"    live_balance = {av.get('live_balance')}")
            print(f"    debits(used) = {ut.get('debits')}")
            print(f"    span         = {ut.get('span')}")
            print(f"    exposure     = {ut.get('exposure')}")
        except Exception as e:
            print(f"  kite.margins() FAILED: {e}")

    else:
        print("  [Layer 1] No KiteConnect session — skipping raw API trace")
        print("  (This account is in mock mode or auth failed)")

    # ── Layer 2: Adapter output ───────────────────────────────────────
    print("\n  [Layer 2] adapter.get_holdings()")
    try:
        t0 = time.monotonic()
        holdings = adapter.get_holdings(account_id)
        ms = (time.monotonic() - t0) * 1000
        print(f"  {len(holdings)} Holding objects in {ms:.0f} ms")
        total_invested = 0.0
        total_current  = 0.0
        total_pnl_h    = 0.0
        for h in holdings[:5]:
            print(
                f"    {h.symbol:<20} qty={h.quantity}  avg={h.avg_price:.2f}  "
                f"ltp={h.ltp:.2f}  invested={h.invested_value:,.0f}  "
                f"current={h.current_value:,.0f}  pnl={h.pnl:+,.0f}"
            )
            total_invested += h.invested_value
            total_current  += h.current_value
            total_pnl_h    += h.pnl
        if len(holdings) > 5:
            for h in holdings[5:]:
                total_invested += h.invested_value
                total_current  += h.current_value
                total_pnl_h    += h.pnl
            print(f"    ... ({len(holdings) - 5} more)")

        print(f"\n  ADAPTER TOTALS:")
        print(f"    total_invested_value = {total_invested:,.2f}")
        print(f"    total_holdings_value = {total_current:,.2f}")
        print(f"    holdings_pnl         = {total_pnl_h:+,.2f}")

        ltp_zero = [h.symbol for h in holdings if h.ltp == 0]
        if ltp_zero:
            print(f"\n  WARNING: ltp=0 for {ltp_zero}")
            print(f"  → current_value = invested_value (cost-basis fallback)")

    except Exception as e:
        print(f"  adapter.get_holdings() FAILED: {e}")

    # ── Layer 3: Margin ───────────────────────────────────────────────
    print("\n  [Layer 3] adapter.get_margin()")
    try:
        margin = adapter.get_margin(account_id)
        if margin:
            print(f"    available_cash   = {margin.available_cash:,.2f}")
            print(f"    net_available    = {margin.net_available:,.2f}")
            print(f"    used_margin      = {margin.used_margin:,.2f}")
            print(f"    total_collateral = {margin.total_collateral:,.2f}")
        else:
            print("    get_margin() returned None")
    except Exception as e:
        print(f"  adapter.get_margin() FAILED: {e}")

    # ── Layer 4: PortfolioService ─────────────────────────────────────
    print("\n  [Layer 4] PortfolioService.get_account_summary()")
    from services.market_data_service import MarketDataService
    from services.portfolio_service import PortfolioService

    md_svc = MarketDataService(settings)
    md_svc.initialize()

    portfolio_svc = PortfolioService(account_svc, md_svc)
    try:
        t0 = time.monotonic()
        summary = portfolio_svc.get_account_summary(account_id)
        ms = (time.monotonic() - t0) * 1000
        if summary:
            print(f"  AccountSummary in {ms:.0f} ms:")
            print(f"    total_holdings_value = {summary.total_holdings_value:,.2f}")
            print(f"    total_invested_value = {summary.total_invested_value:,.2f}")
            print(f"    holdings_pnl         = {summary.holdings_pnl:+,.2f}")
            print(f"    positions_pnl        = {summary.positions_pnl:+,.2f}")
            print(f"    day_pnl              = {summary.day_pnl:+,.2f}")
            print(f"    available_cash       = {summary.available_cash:,.2f}")
            print(f"    net_available        = {summary.net_available:,.2f}")
            print(f"    used_margin          = {summary.used_margin:,.2f}")
            print(f"    total_collateral     = {summary.total_collateral:,.2f}")
            print(f"    net_worth            = {summary.net_worth:,.2f}")
        else:
            print("  get_account_summary() returned None")
    except Exception as e:
        print(f"  get_account_summary() FAILED: {e}")

hr("DONE")
print("Run this script on the VPS to compare each layer's output.")
print("If Layer 1 (raw API) shows correct quantities but Layer 2 shows 0,")
print("the adapter module is stale in cache. Restart the Streamlit server.")
print()
print("If all layers show 0 holdings_value, the LTP is 0 (pre-market)")
print("and the cost-basis fallback in schemas/holding.py should be active.")
print("Check that schemas/holding.py has been updated on the VPS.")
