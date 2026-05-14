"""
5paisa broker adapter — live implementation using py5paisa.

Authentication flow (token-based, no TOTP required):
    from py5paisa import FivePaisaClient
    cred = {
        "APP_NAME": ..., "APP_SOURCE": "27773",
        "USER_ID": ..., "USER_KEY": ...,
        "ENCRYPTION_KEY": ..., "PASSWORD": "dummy",
    }
    client = FivePaisaClient(cred=cred)
    client.set_access_token(access_token, client_code)

API response field reference (verified against py5paisa V3/V4 endpoints):

holdings()  →  body.Data  (list of dicts):
    NSECode          — NSE trading symbol (e.g. "RELIANCE"); "" for BSE-only scrips
    BSECode          — BSE numeric code
    ISIN             — ISIN code
    Price            — average buy price (cost basis per share)
    CurrentPrice     — current LTP
    CostValue        — total invested value (Price × Qty)
    CurrentValue     — current market value (CurrentPrice × Qty)
    Qty              — total quantity (free + T1 + pledged; analogous to Zerodha total_qty)
    DpQty            — DP settled / freely tradeable quantity
    EarmarkQty       — pledged / earmarked quantity
    BrokerName       — full company name
    Exchange         — "N" (NSE) or "B" (BSE)

positions()  →  body.NetPositionDetail  (list of dicts):
    Exch             — "N" (NSE) or "B" (BSE)
    ExchType         — "D" (derivatives/F&O), "C" (cash/equity)
    Symbol           — full trading symbol (e.g. "NIFTY25JUNFUT", "BANKNIFTY25JUN44000PE")
    NetQty           — net position quantity (+ long, − short)
    BuyAvgRate       — average buy price
    SellAvgRate      — average sell price (> 0 only when short or partial sell)
    LTP              — last traded price
    MTOM             — day mark-to-market P&L (unrealised, from session reference)
    BookedPL         — realised P&L (closed legs today)
    SLTP             — previous close / settlement price (used for day P&L calc)
    ExpDate          — expiry date in "/Date(ms)/" format (F&O only)
    StrikeRate       — strike price (options only; 0 for futures/equity)
    ScripType        — "CE", "PE" (options); "XX" (futures when ExchType="D");
                       "EQ"/"EQNRML" (equity when ExchType="C")
    OrderFor         — "I" (intraday/MIS), "D" (delivery/CNC), "H" (NRML hold)
    Multiplier       — lot size (1 for equity, 50/75/etc. for F&O)

margin()  →  body.EquityMargin  (list with ONE dict):
    AvailableBalance — usable cash balance
    BlockedAmount    — margin currently blocked (SPAN + exposure + option premium)
    Collateral       — pledged-holdings collateral value (post-haircut)
    TotalBalance     — AvailableBalance + BlockedAmount (approximate)
    Ledger           — ledger balance
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from brokers.zerodha.adapter import _NSE_SECTOR         # shared sector lookup
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)

# Regex to strip the underlying from an F&O symbol.
# Matches: NIFTY25JUNFUT → NIFTY, BANKNIFTY25JUN44000PE → BANKNIFTY
_FNO_UNDERLYING_RE = re.compile(r"^([A-Z&]+?)(\d{2}[A-Z]{3}|\d{5})")

# 5paisa date format: "/Date(1750000000000)/" — milliseconds since epoch
_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _extract_underlying(symbol: str) -> str:
    m = _FNO_UNDERLYING_RE.match(symbol)
    return m.group(1) if m else symbol


def _parse_date(raw: str) -> Optional[str]:
    """Convert 5paisa "/Date(ms)/" to "YYYY-MM-DD", or return None."""
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if m:
        ts_ms = int(m.group(1))
        if ts_ms == 0:
            return None
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    # Already a plain date string
    return raw if raw.strip() else None


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return default


def _map_exchange(exch: str, exch_type: str) -> str:
    """Map 5paisa Exch/ExchType to human-readable exchange string."""
    if exch_type == "D":
        return "NFO" if exch == "N" else "BFO"
    return "NSE" if exch == "N" else "BSE"


def _map_instrument_type(scrip_type: str, exch_type: str) -> str:
    """Map 5paisa ScripType + ExchType to normalised instrument_type."""
    if scrip_type == "CE":
        return "CE"
    if scrip_type == "PE":
        return "PE"
    if exch_type == "D":
        return "FUT"   # "XX" in derivatives segment means futures
    return "EQ"


def _map_product(exch_type: str, order_for: str) -> str:
    """Map 5paisa ExchType + OrderFor to product code (MIS/CNC/NRML)."""
    if exch_type == "D":
        return "NRML"
    if order_for == "I":
        return "MIS"
    return "CNC"        # "D" (delivery) or "H" (hold)


class FivePaisaAdapter(BrokerAdapter):
    """
    Live 5paisa adapter.  One instance is created per account by AccountService.

    Authentication: supply APP_NAME / APP_SOURCE / USER_ID / USER_KEY /
    ENCRYPTION_KEY / PASSWORD credentials plus an ACCESS_TOKEN and CLIENT_CODE
    obtained from the 5paisa portal.  Call authenticate() on startup; the
    adapter holds the FivePaisaClient session for the lifetime of the process.
    """

    def __init__(self):
        self._client: Optional[object] = None       # FivePaisaClient instance
        self._client_code: str = ""
        self._account_id: str = ""
        self._credentials: dict = {}
        self._last_auth_error: Optional[str] = None

    # ------------------------------------------------------------------
    # BrokerAdapter protocol
    # ------------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return "fivepaisa"

    @property
    def last_auth_error(self) -> Optional[str]:
        return self._last_auth_error

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        """
        Authenticate using a pre-obtained access_token + client_code.
        Calls margin() to verify the token is valid.
        """
        self._last_auth_error = None

        try:
            from py5paisa import FivePaisaClient
        except ImportError:
            self._last_auth_error = (
                "py5paisa not installed. Run: pip install py5paisa"
            )
            logger.error(self._last_auth_error)
            return False

        required = {
            "app_name":       credentials.get("app_name", ""),
            "app_source":     credentials.get("app_source", ""),
            "user_id":        credentials.get("user_id", ""),
            "user_key":       credentials.get("user_key", ""),
            "encryption_key": credentials.get("encryption_key", ""),
            "access_token":   credentials.get("access_token", ""),
            "client_code":    credentials.get("client_code", ""),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            self._last_auth_error = f"Missing credentials for '{account_id}': {missing}"
            logger.error(self._last_auth_error)
            return False

        try:
            cred = {
                "APP_NAME":       required["app_name"],
                "APP_SOURCE":     required["app_source"],
                "USER_ID":        required["user_id"],
                "USER_KEY":       required["user_key"],
                "ENCRYPTION_KEY": required["encryption_key"],
                "PASSWORD":       credentials.get("password", "dummy"),
            }
            client = FivePaisaClient(cred=cred)
            client.set_access_token(
                required["access_token"],
                required["client_code"],
            )

            # Verify token with a lightweight API call.
            # margin() returns None on auth failure; [] or [dict] on success.
            test = client.margin()
            if test is None:
                self._last_auth_error = (
                    f"5paisa token verification failed for '{account_id}'. "
                    "Check ACCESS_TOKEN and CLIENT_CODE."
                )
                logger.error(self._last_auth_error)
                return False

            self._client = client
            self._client_code = required["client_code"]
            self._account_id = account_id
            self._credentials = credentials
            logger.info(
                "5paisa authenticated '%s' (client_code=%s)",
                account_id, self._client_code,
            )
            return True

        except Exception as exc:
            self._last_auth_error = str(exc)
            logger.error("5paisa auth failed for '%s': %s", account_id, exc)
            return False

    def is_session_valid(self, account_id: str) -> bool:
        return self._client is not None and account_id == self._account_id

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        if not self.is_session_valid(account_id):
            return None
        display_name = (
            self._credentials.get("display_name")
            or f"5paisa ({self._client_code})"
        )
        return AccountInfo(
            account_id=account_id,
            broker="fivepaisa",
            display_name=display_name,
            owner=display_name,
            user_id=self._client_code,
            is_active=True,
            metadata={"client_code": self._client_code},
        )

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    def get_holdings(self, account_id: str) -> List[Holding]:
        if not self.is_session_valid(account_id):
            return []
        try:
            raw = self._client.holdings()
        except Exception as exc:
            logger.error("5paisa get_holdings failed for '%s': %s", account_id, exc)
            return []

        if not raw:
            return []

        holdings: List[Holding] = []
        for r in raw:
            # Confirmed field names from live py5paisa response:
            #   Symbol, Quantity, AvgRate, CurrentPrice, Exch
            symbol = (r.get("Symbol") or "").strip()
            if not symbol:
                logger.warning("5paisa holding skipped — 'Symbol' missing in row: %s", r)
                continue

            qty = _safe_float(r.get("Quantity"))
            if qty <= 0:
                logger.debug("5paisa holding skipped — zero Quantity for %s", symbol)
                continue

            avg_price    = _safe_float(r.get("AvgRate"))
            ltp          = _safe_float(r.get("CurrentPrice"))
            exchange_raw = (r.get("Exch") or "N").strip()
            exchange     = "NSE" if exchange_raw == "N" else "BSE"

            # ISIN not present in actual API response — leave blank
            # day_change left at 0; overwritten by md_svc ohlc injection each render
            sector = _NSE_SECTOR.get(symbol, "Other")

            h = Holding(
                account_id=account_id,
                broker="fivepaisa",
                symbol=symbol,
                exchange=exchange,
                isin="",
                quantity=qty,
                avg_price=avg_price,
                ltp=ltp,
                sector=sector,
                instrument_type="EQ",
                tradingsymbol=symbol,
            )
            holdings.append(h)

        logger.info("5paisa get_holdings '%s': %d holdings", account_id, len(holdings))
        return holdings

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self, account_id: str) -> List[Position]:
        if not self.is_session_valid(account_id):
            return []
        try:
            raw = self._client.positions()
        except Exception as exc:
            logger.error("5paisa get_positions failed for '%s': %s", account_id, exc)
            return []

        if not raw:
            return []

        # Log the first row's keys so field names can be verified against live data
        if raw and isinstance(raw[0], dict):
            logger.info(
                "5paisa positions payload keys (first row): %s",
                list(raw[0].keys()),
            )

        positions: List[Position] = []
        for r in raw:
            net_qty = _safe_int(r.get("NetQty"))
            if net_qty == 0:
                continue

            exch      = (r.get("Exch") or "N").strip()
            exch_type = (r.get("ExchType") or "C").strip()
            scrip_type = (r.get("ScripType") or "EQ").strip()
            order_for  = (r.get("OrderFor") or "D").strip()
            symbol     = (r.get("Symbol") or "").strip()

            instrument_type = _map_instrument_type(scrip_type, exch_type)
            product         = _map_product(exch_type, order_for)
            exchange        = _map_exchange(exch, exch_type)
            underlying      = _extract_underlying(symbol)

            buy_avg  = _safe_float(r.get("BuyAvgRate"))
            sell_avg = _safe_float(r.get("SellAvgRate"))
            # avg_price = cost basis from the dominant side
            avg_price = buy_avg if net_qty > 0 else sell_avg

            ltp       = _safe_float(r.get("LTP"))
            mtom      = _safe_float(r.get("MTOM"))        # day M2M P&L
            booked_pl = _safe_float(r.get("BookedPL"))
            lot_size  = _safe_int(r.get("Multiplier"), 1) or 1

            # Unrealised P&L from cost basis
            if net_qty > 0:
                unrealised = round((ltp - avg_price) * abs(net_qty), 2)
            else:
                unrealised = round((avg_price - ltp) * abs(net_qty), 2)

            # F&O fields
            expiry_raw = r.get("ExpDate") or ""
            expiry     = _parse_date(expiry_raw)
            strike_raw = _safe_float(r.get("StrikeRate"))
            strike     = strike_raw if strike_raw > 0 else None

            buy_qty  = _safe_int(r.get("BuyQty"))
            sell_qty = _safe_int(r.get("SellQty"))
            value    = round(abs(net_qty) * ltp, 2)

            pos = Position(
                account_id=account_id,
                broker="fivepaisa",
                symbol=symbol,
                exchange=exchange,
                product=product,
                instrument_type=instrument_type,
                quantity=net_qty,
                avg_price=avg_price,
                ltp=ltp,
                pnl=unrealised,
                day_pnl=mtom,           # session M2M — same semantics as Zerodha's m2m
                value=value,
                buy_quantity=buy_qty,
                sell_quantity=sell_qty,
                lot_size=lot_size,
                expiry=expiry,
                strike=strike,
                underlying=underlying,
                tradingsymbol=symbol,
            )
            positions.append(pos)

            logger.debug(
                "5paisa position: %s type=%s qty=%d avg=%.2f ltp=%.2f "
                "unrealised=%.2f mtom=%.2f underlying=%s",
                symbol, instrument_type, net_qty, avg_price, ltp,
                unrealised, mtom, underlying,
            )

        logger.info("5paisa get_positions '%s': %d open positions", account_id, len(positions))
        return positions

    # ------------------------------------------------------------------
    # Margin
    # ------------------------------------------------------------------

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        if not self.is_session_valid(account_id):
            return None
        try:
            raw = self._client.margin()
        except Exception as exc:
            logger.error("5paisa get_margin '%s' API call failed: %s", account_id, exc)
            return None

        if not raw:
            logger.warning("5paisa get_margin '%s': empty EquityMargin response", account_id)
            return MarginInfo(account_id=account_id, broker="fivepaisa")

        # margin() returns a list; take the first (and usually only) element.
        # Confirmed field names from live py5paisa response:
        #   Ledgerbalance, NetAvailableMargin, MarginUtilized,
        #   GrossHoldingValue, DPFreeStockValue, DerivativeMargin, OptionsPremium
        m = raw[0] if isinstance(raw, list) else raw

        if not isinstance(m, dict):
            logger.error(
                "5paisa get_margin '%s': unexpected payload type %s — raw=%s",
                account_id, type(m).__name__, raw,
            )
            return MarginInfo(account_id=account_id, broker="fivepaisa")

        available     = _safe_float(m.get("Ledgerbalance"))
        net_available = _safe_float(m.get("NetAvailableMargin"))
        blocked       = _safe_float(m.get("MarginUtilized"))
        # GrossHoldingValue = total DP holdings; DPFreeStockValue = free portion
        collateral        = _safe_float(m.get("GrossHoldingValue"))
        deriv_margin      = _safe_float(m.get("DerivativeMargin"))
        option_premium    = _safe_float(m.get("OptionsPremium"))

        logger.info(
            "5paisa get_margin '%s': ledger=%.2f net_avail=%.2f "
            "margin_used=%.2f gross_holdings=%.2f deriv=%.2f opt_prem=%.2f",
            account_id, available, net_available,
            blocked, collateral, deriv_margin, option_premium,
        )

        return MarginInfo(
            account_id=account_id,
            broker="fivepaisa",
            available_cash=available,
            net_available=net_available,
            used_margin=blocked,
            total_collateral=collateral,
            span_margin=deriv_margin,
            option_premium=option_premium,
        )

    # ------------------------------------------------------------------
    # Account summary (delegates to individual methods)
    # ------------------------------------------------------------------

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        """Compute AccountSummary from live API data. Used by the adapter directly
        only when portfolio_service is not involved (e.g., debug calls)."""
        info = self.get_account_info(account_id)
        if not info:
            return None

        holdings  = self.get_holdings(account_id)
        positions = self.get_positions(account_id)
        margin    = self.get_margin(account_id)

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested       = sum(h.invested_value for h in holdings)
        holdings_pnl         = sum(h.pnl for h in holdings)
        positions_pnl        = sum(p.pnl for p in positions)
        holdings_day_pnl     = sum(h.day_change * h.quantity for h in holdings)
        positions_day_pnl    = sum(p.day_pnl for p in positions)
        day_pnl              = round(holdings_day_pnl + positions_day_pnl, 2)

        available_cash   = margin.available_cash   if margin else 0.0
        net_available    = margin.net_available    if margin else 0.0
        used_margin      = margin.used_margin      if margin else 0.0
        total_collateral = margin.total_collateral if margin else 0.0

        net_worth = round(total_holdings_value + available_cash + positions_pnl, 2)

        return AccountSummary(
            account_id=account_id,
            broker="fivepaisa",
            display_name=info.display_name,
            owner=info.owner,
            total_holdings_value=round(total_holdings_value, 2),
            total_invested_value=round(total_invested, 2),
            holdings_pnl=round(holdings_pnl, 2),
            holdings_pnl_pct=(
                round((holdings_pnl / total_invested) * 100, 2) if total_invested else 0.0
            ),
            positions_pnl=round(positions_pnl, 2),
            day_pnl=day_pnl,
            holdings_day_pnl=round(holdings_day_pnl, 2),
            available_cash=available_cash,
            net_available=net_available,
            used_margin=used_margin,
            total_collateral=total_collateral,
            net_worth=net_worth,
        )

    # ------------------------------------------------------------------
    # Subscribed symbols (for MD service symbol set building)
    # ------------------------------------------------------------------

    def get_subscribed_symbols(self, account_id: str) -> List[str]:
        """Return symbols from live holdings + positions for quote subscription."""
        symbols: List[str] = []
        for h in self.get_holdings(account_id):
            if h.instrument_type != "MF":
                symbols.append(h.symbol)
        for p in self.get_positions(account_id):
            symbols.append(p.symbol)
            if p.underlying and p.underlying != p.symbol:
                symbols.append(p.underlying)
        return list(dict.fromkeys(symbols))
