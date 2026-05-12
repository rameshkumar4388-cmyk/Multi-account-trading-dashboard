"""
Zerodha KiteConnect broker adapter.

Requires kiteconnect >= 5.0 and a valid access_token.

Field-mapping reference (verified against Zerodha KiteConnect API):

holdings() response keys used here:
  tradingsymbol, exchange, isin, instrument_token
  quantity            — free/tradeable (EXCLUDES T1, auth-pending, and pledged)
  t1_quantity         — T+1 unsettled (bought today/yesterday, settling tomorrow)
  authorised_quantity — pledge initiated but CDSL depository OTP not yet done
                        (shares frozen in this state; NOT in any other qty field)
  collateral_quantity — pledge approved and active (Zerodha v3 canonical field)
                        verified live: fully-pledged accounts show ONLY this field > 0
  used_quantity       — legacy/alternative pledge field (older API or margin-in-use
                        indicator); may be 0 even when collateral_quantity > 0
  opening_quantity    — total at session open; stale intraday, NOT a primary ownership
                        field — used only as last-resort fallback
  average_price       — cost basis per share
  last_price          — current LTP
  close_price         — previous session close (for day-change calc)
  day_change          — per-share price change vs. close_price
  day_change_percentage
  pnl                 — broker-computed unrealized P&L
  collateral_type     — "margin" if pledged, "" otherwise

  TOTAL OWNED = quantity + t1_quantity + authorised_quantity
                + collateral_quantity
  used_quantity is a margin-utilisation indicator, not a share count.
  It is NOT added — doing so would double-count pledged shares.

positions() response keys used here (net positions):
  tradingsymbol, exchange, product, instrument_type
  quantity          — net quantity (+ long, - short)
  average_price     — average entry price
  last_price        — current LTP
  pnl               — unrealized P&L for the net position
  m2m               — day mark-to-market P&L (NOT "day_m2m" — that field does not exist)
  realised          — realized P&L from intraday squared positions
  unrealised        — unrealized P&L (= pnl for net)
  value             — monetary value (negative for buy-side in Zerodha's convention)
  buy_quantity, sell_quantity, lot_size, expiry, strike

margins() response structure:
  equity.available.cash           — pure cash balance
  equity.available.live_balance   — total available (cash + collateral - debits)
  equity.available.collateral     — pledged collateral value (after haircut)
  equity.utilised.debits          — total margin blocked
  equity.utilised.span            — SPAN margin
  equity.utilised.exposure        — exposure margin
  equity.utilised.option_premium  — option premium blocked
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)

# Regex to isolate the underlying name from an F&O trading symbol.
# Zerodha format examples:
#   NIFTY25JUNFUT       → NIFTY
#   BANKNIFTY25JUN44000PE → BANKNIFTY
#   RELIANCE25JUNFUT    → RELIANCE
#   NIFTY2561924500CE   → NIFTY   (weekly option with numeric expiry)
_FNO_UNDERLYING_RE = re.compile(r"^([A-Z&]+?)(\d{2}[A-Z]{3}|\d{5})")


def _extract_underlying(tradingsymbol: str, instrument_type: str) -> str:
    """Return the underlying asset name from a Zerodha trading symbol.

    Always run the regex — pure equity symbols contain no digit-date pattern
    so they fall through to the tradingsymbol fallback correctly.
    This also handles the case where instrument_type is missing from the API
    response and defaults to 'EQ' (the Zerodha positions endpoint sometimes
    omits this field).
    """
    m = _FNO_UNDERLYING_RE.match(tradingsymbol)
    return m.group(1) if m else tradingsymbol


def _friendly_error(exc: Exception) -> str:
    """Map kiteconnect exception types to actionable human-readable messages."""
    name = type(exc).__name__
    msg = str(exc)
    if "TokenException" in name or "InvalidToken" in name or "token" in msg.lower():
        return (
            "Access token invalid or expired. "
            "Log in at kite.zerodha.com, generate a new token, and update ACCESS_TOKEN in .env."
        )
    if "NetworkException" in name or "ConnectionError" in name:
        return "Network error — check your internet connection and try again."
    if "TwoFAException" in name:
        return "Two-factor authentication required — complete login in the Zerodha app."
    if "UserException" in name:
        return f"User error: {msg}"
    if "InputException" in name:
        return f"Bad request (check api_key / credentials): {msg}"
    if "DataException" in name:
        return f"Zerodha API data error: {msg}"
    if "PermissionException" in name:
        return f"Permission denied — check API subscription: {msg}"
    return f"{name}: {msg}"


class ZerodhaAdapter(BrokerAdapter):
    """
    Live Zerodha adapter using KiteConnect REST API.
    One adapter instance manages all accounts via separate KiteConnect
    sessions keyed by account_id.

    After a failed authenticate() call, last_auth_error holds a
    human-readable explanation of why it failed.
    """

    def __init__(self):
        self._sessions: Dict[str, object] = {}
        self._profiles: Dict[str, dict] = {}   # profile cached at auth time
        self._last_auth_error: Optional[str] = None

    @property
    def broker_name(self) -> str:
        return "zerodha"

    @property
    def last_auth_error(self) -> Optional[str]:
        return self._last_auth_error

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        self._last_auth_error = None

        try:
            from kiteconnect import KiteConnect
        except ImportError:
            self._last_auth_error = (
                "kiteconnect package not installed. Run: pip install kiteconnect"
            )
            logger.error(self._last_auth_error)
            return False

        api_key      = (credentials.get("api_key") or "").strip()
        access_token = (credentials.get("access_token") or "").strip()

        if not api_key:
            self._last_auth_error = f"api_key missing for account '{account_id}'"
            logger.error(self._last_auth_error)
            return False
        if not access_token:
            self._last_auth_error = f"access_token missing for account '{account_id}'"
            logger.error(self._last_auth_error)
            return False

        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            profile = kite.profile()
            self._sessions[account_id] = kite
            self._profiles[account_id] = profile   # cache for get_account_info
            logger.info(
                "Authenticated Zerodha account '%s' (user_id=%s name=%s)",
                account_id,
                profile.get("user_id", "?"),
                profile.get("user_name", "?"),
            )
            return True

        except Exception as exc:
            self._last_auth_error = _friendly_error(exc)
            logger.error("Zerodha auth failed for '%s': %s", account_id, self._last_auth_error)
            return False

    def is_session_valid(self, account_id: str) -> bool:
        return account_id in self._sessions

    def get_kite_session(self, account_id: str):
        return self._sessions.get(account_id)

    def _kite(self, account_id: str):
        session = self._sessions.get(account_id)
        if not session:
            raise RuntimeError(
                f"No active Zerodha session for account '{account_id}'. "
                "Call authenticate() first."
            )
        return session

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    def get_holdings(self, account_id: str) -> List[Holding]:
        equity = self._get_equity_holdings(account_id)
        mf     = self._get_mf_holdings(account_id)
        return equity + mf

    def _get_equity_holdings(self, account_id: str) -> List[Holding]:
        try:
            raw = self._kite(account_id).holdings()
        except Exception as exc:
            logger.error("get_holdings failed for '%s': %s", account_id, exc)
            return []

        logger.info("get_holdings '%s': %d equity rows", account_id, len(raw))

        holdings: List[Holding] = []
        for r in raw:
            # ── Ownership quantity ─────────────────────────────────────
            #
            # quantity            = free/tradeable (can sell today); float for
            #                       fractional ETF units (e.g. LIQUIDBEES-F)
            # t1_quantity         = T+1 pending settlement
            # authorised_quantity = pledge initiated, CDSL OTP not done yet
            # collateral_quantity = pledge approved and active (v3 canonical)
            #
            # opening_quantity    = stale session-open snapshot; last-resort
            #                       fallback only when all other fields are 0.
            free_qty    = float(r.get("quantity", 0)            or 0)
            t1_qty      = float(r.get("t1_quantity", 0)         or 0)
            auth_qty    = float(r.get("authorised_quantity", 0) or 0)
            collat_qty  = float(r.get("collateral_quantity", 0) or 0)
            # collateral_quantity is the canonical pledged-shares field (v3 API).
            # Do not mix in used_quantity — it is a margin-utilisation indicator,
            # not a separate block of shares, and would cause double-counting.
            pledged_qty = collat_qty
            total_qty   = free_qty + t1_qty + auth_qty + pledged_qty

            # Last-resort fallback: opening_quantity captures transient API
            # states not covered by the explicit fields above.
            if total_qty <= 0:
                opening_qty = int(r.get("opening_quantity", 0) or 0)
                if opening_qty > 0:
                    total_qty = opening_qty
                    logger.warning(
                        "Holding %s: all primary qty fields=0, "
                        "using opening_quantity=%d as fallback",
                        r.get("tradingsymbol"), opening_qty,
                    )

            if total_qty <= 0:
                logger.debug(
                    "Skipping %s: free=%.4f t1=%.4f auth=%.4f collat=%.4f "
                    "opening=%.4f — all zero",
                    r.get("tradingsymbol"),
                    free_qty, t1_qty, auth_qty, collat_qty,
                    float(r.get("opening_quantity", 0) or 0),
                )
                continue

            avg_price   = float(r.get("average_price", 0))
            last_price  = float(r.get("last_price", 0))
            close_price = float(r.get("close_price", 0))
            # Use close_price when last_price is 0 (halted, pre-market, newly listed).
            # Note: holdings API last_price = EOD snapshot; live prices come from the
            # quote feed via LTP injection in portfolio_service._inject_ltp_holdings().
            effective_ltp = last_price if last_price > 0 else close_price

            # day_change from Zerodha is per-share price change vs. close_price
            day_change     = float(r.get("day_change", 0))
            day_change_pct = float(r.get("day_change_percentage", 0))

            # Fallback: compute day_change from close_price if API returns 0
            if day_change == 0 and close_price > 0 and effective_ltp > 0:
                day_change = round(effective_ltp - close_price, 2)
                if close_price > 0:
                    day_change_pct = round((day_change / close_price) * 100, 2)

            collateral_type = r.get("collateral_type", "")

            h = Holding(
                account_id=account_id,
                broker="zerodha",
                symbol=r.get("tradingsymbol", ""),
                exchange=r.get("exchange", "NSE"),
                isin=r.get("isin", ""),
                quantity=total_qty,
                avg_price=avg_price,
                ltp=effective_ltp,
                sector=r.get("sector", "Unknown"),
                instrument_type="EQ",
                tradingsymbol=r.get("tradingsymbol", ""),
            )
            h.day_change     = day_change
            h.day_change_pct = day_change_pct
            # pnl is computed by Holding.__post_init__ as qty × (ltp − avg_price).
            # The quote feed will inject live LTP via _inject_ltp_holdings() which
            # calls h.update_ltp(live_ltp) → pnl = qty × (live_ltp − avg_price).
            # Do NOT override with the API pnl field — it uses EOD close prices.

            logger.debug(
                "Holding: %s total=%.4f "
                "(free=%.4f t1=%.4f auth=%.4f collat=%.4f) "
                "avg=%.2f ltp=%.2f pnl=%.2f",
                r.get("tradingsymbol"), total_qty,
                free_qty, t1_qty, auth_qty, collat_qty,
                avg_price, effective_ltp, h.pnl,
            )
            holdings.append(h)

        logger.info("get_holdings '%s': %d equity holdings", account_id, len(holdings))
        return holdings

    def _get_mf_holdings(self, account_id: str) -> List[Holding]:
        """Fetch mutual fund holdings via kite.mf_holdings() and return as Holding objects."""
        try:
            raw = self._kite(account_id).mf_holdings()
        except Exception as exc:
            logger.warning("mf_holdings '%s': not available or failed: %s", account_id, exc)
            return []

        if not raw:
            return []

        logger.info("mf_holdings '%s': %d MF rows", account_id, len(raw))
        holdings: List[Holding] = []

        for r in raw:
            # Log the full raw row so the debug page can show exact field semantics
            logger.info(
                "MF raw row [%s]: quantity=%.4f pledged_quantity=%.4f t1_quantity=%.4f "
                "average_price=%.4f last_price=%.4f pnl=%.2f",
                r.get("tradingsymbol", r.get("fund", "?")),
                float(r.get("quantity", 0) or 0),
                float(r.get("pledged_quantity", 0) or 0),
                float(r.get("t1_quantity", 0) or 0),
                float(r.get("average_price", 0) or 0),
                float(r.get("last_price", 0) or 0),
                float(r.get("pnl", 0) or 0),
            )
            # quantity in mf_holdings() = TOTAL units (free + pledged combined).
            # pledged_quantity is a SUBSET of quantity, NOT additional units.
            # Adding pledged_quantity again would double-count pledged units.
            total_qty = float(r.get("quantity", 0) or 0) + float(r.get("t1_quantity", 0) or 0)

            if total_qty <= 0:
                continue

            avg_price  = float(r.get("average_price", 0) or 0)
            last_price = float(r.get("last_price", 0)    or 0)

            # Trading symbol for MF: prefer tradingsymbol, fall back to ISIN or fund name
            tradingsymbol = (
                r.get("tradingsymbol") or r.get("isin") or r.get("fund", "")
            )
            fund_name = r.get("fund", tradingsymbol)

            h = Holding(
                account_id=account_id,
                broker="zerodha",
                symbol=tradingsymbol,
                exchange="MF",          # distinguishes MF from equity in all downstream logic
                isin=r.get("isin", ""),
                quantity=total_qty,
                avg_price=avg_price,
                ltp=last_price,         # NAV — EOD only; no live injection attempted
                sector="Mutual Funds",
                instrument_type="MF",
                tradingsymbol=tradingsymbol,
            )
            # Store full fund name so UI can display it
            h._fund_name = fund_name

            logger.debug(
                "MF holding: %s qty=%.4f avg=%.4f nav=%.4f pnl=%.2f",
                tradingsymbol, total_qty, avg_price, last_price, h.pnl,
            )
            holdings.append(h)

        logger.info("mf_holdings '%s': %d MF holdings loaded", account_id, len(holdings))
        return holdings

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self, account_id: str) -> List[Position]:
        try:
            raw_all = self._kite(account_id).positions()
        except Exception as exc:
            logger.error("get_positions failed for '%s': %s", account_id, exc)
            return []

        net_positions = raw_all.get("net", [])
        logger.debug(
            "get_positions '%s': %d net positions", account_id, len(net_positions)
        )

        positions: List[Position] = []
        for r in net_positions:
            qty = int(r.get("quantity", 0))
            if qty == 0:
                continue

            itype          = r.get("instrument_type", "EQ")
            tradingsymbol  = r.get("tradingsymbol", "")
            last_price     = float(r.get("last_price", 0))
            avg_price      = float(r.get("average_price", 0))
            lot_size       = int(r.get("lot_size", 1)) if itype != "EQ" else 1

            # P&L fields
            # pnl       = unrealized P&L for the net position
            # m2m       = day mark-to-market P&L  ← Zerodha uses "m2m", NOT "day_m2m"
            # realised  = realized P&L from intraday squared-off legs
            unrealised_pnl = float(r.get("pnl", r.get("unrealised", 0)))
            day_m2m        = float(r.get("m2m", r.get("day_m2m", 0)))  # "m2m" is the correct key
            realised_pnl   = float(r.get("realised", 0))

            # Underlying: parse from tradingsymbol for F&O
            underlying = _extract_underlying(tradingsymbol, itype)

            # Expiry / strike
            expiry_raw = r.get("expiry", "")
            expiry     = str(expiry_raw) if expiry_raw else None
            strike_raw = r.get("strike", 0)
            strike     = float(strike_raw) if strike_raw else None

            pos = Position(
                account_id=account_id,
                broker="zerodha",
                symbol=tradingsymbol,
                exchange=r.get("exchange", "NSE"),
                product=r.get("product", "MIS"),
                instrument_type=itype,
                quantity=qty,
                avg_price=avg_price,
                ltp=last_price,
                pnl=unrealised_pnl,
                day_pnl=day_m2m,          # Correctly mapped from "m2m"
                value=abs(qty) * last_price * lot_size,  # always-positive display value
                buy_quantity=int(r.get("buy_quantity", 0)),
                sell_quantity=int(r.get("sell_quantity", 0)),
                lot_size=lot_size,
                expiry=expiry,
                strike=strike,
                underlying=underlying,
                tradingsymbol=tradingsymbol,
            )

            logger.debug(
                "Position: %s type=%s qty=%d avg=%.2f ltp=%.2f "
                "unrealised=%.2f m2m=%.2f realised=%.2f underlying=%s",
                tradingsymbol, itype, qty, avg_price, last_price,
                unrealised_pnl, day_m2m, realised_pnl, underlying,
            )
            positions.append(pos)

        logger.info(
            "get_positions '%s': %d open positions", account_id, len(positions)
        )
        return positions

    # ------------------------------------------------------------------
    # Margin
    # ------------------------------------------------------------------

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        try:
            funds = self._kite(account_id).margins()
        except Exception as exc:
            logger.error("get_margin failed for '%s': %s", account_id, exc)
            return None

        equity    = funds.get("equity", {})
        available = equity.get("available", {})
        utilised  = equity.get("utilised", {})

        # Direct API values — no derivation
        cash       = float(available.get("cash", 0))        # pure cash
        collateral = float(available.get("collateral", 0))  # pledged holdings (post-haircut)

        debits         = float(utilised.get("debits", 0))
        span           = float(utilised.get("span", 0))
        exposure       = float(utilised.get("exposure", 0))
        option_premium = float(utilised.get("option_premium", 0))

        # Available Margin = Cash + Collateral (gross, before deducting used margin)
        net_available_val = round(cash + collateral, 2)

        logger.debug(
            "get_margin '%s': cash=%.2f collateral=%.2f "
            "available=%.2f debits=%.2f",
            account_id, cash, collateral, net_available_val, debits,
        )

        return MarginInfo(
            account_id=account_id,
            broker="zerodha",
            available_cash=cash,
            net_available=net_available_val,
            used_margin=debits,
            total_collateral=collateral,
            span_margin=span,
            exposure_margin=exposure,
            option_premium=option_premium,
        )

    # ------------------------------------------------------------------
    # Account summary
    # ------------------------------------------------------------------

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        holdings  = self.get_holdings(account_id)
        positions = self.get_positions(account_id)
        margin    = self.get_margin(account_id)
        info      = self.get_account_info(account_id)

        if not info:
            return None

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested       = sum(h.invested_value for h in holdings)
        holdings_pnl         = sum(h.pnl for h in holdings)
        positions_pnl        = sum(p.pnl for p in positions)
        holdings_day_pnl     = sum(h.day_change * h.quantity for h in holdings)
        day_pnl              = holdings_day_pnl + sum(p.day_pnl for p in positions)
        available_cash   = margin.available_cash   if margin else 0.0
        net_available    = margin.net_available    if margin else 0.0
        used_margin      = margin.used_margin      if margin else 0.0
        total_collateral = margin.total_collateral if margin else 0.0

        # Net worth = holdings market value + cash + open positions MTM P&L
        net_worth = round(total_holdings_value + available_cash + positions_pnl, 2)

        logger.info(
            "AccountSummary '%s': holdings_val=%.2f invested=%.2f "
            "holdings_pnl=%.2f positions_pnl=%.2f day_pnl=%.2f "
            "cash=%.2f net_available=%.2f collateral=%.2f net_worth=%.2f",
            account_id, total_holdings_value, total_invested,
            holdings_pnl, positions_pnl, day_pnl,
            available_cash, net_available, total_collateral, net_worth,
        )

        return AccountSummary(
            account_id=account_id,
            broker="zerodha",
            display_name=info.display_name,
            owner=info.owner,
            total_holdings_value=round(total_holdings_value, 2),
            total_invested_value=round(total_invested, 2),
            holdings_pnl=round(holdings_pnl, 2),
            holdings_pnl_pct=round((holdings_pnl / total_invested) * 100, 2) if total_invested else 0.0,
            positions_pnl=round(positions_pnl, 2),
            day_pnl=round(day_pnl, 2),
            holdings_day_pnl=round(holdings_day_pnl, 2),
            available_cash=available_cash,
            net_available=net_available,
            used_margin=used_margin,
            total_collateral=total_collateral,
            net_worth=net_worth,
        )

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        # Use profile cached at auth time; only call API if cache is empty.
        # This avoids a kite.profile() round-trip on every dashboard refresh.
        profile = self._profiles.get(account_id)
        if not profile:
            try:
                profile = self._kite(account_id).profile()
                self._profiles[account_id] = profile
            except Exception as exc:
                logger.error("get_account_info failed for '%s': %s", account_id, exc)
                return None

        client_id    = profile.get("user_id", "")
        display_name = f"Zerodha ({client_id})" if client_id else "Zerodha"
        return AccountInfo(
            account_id=account_id,
            broker="zerodha",
            display_name=display_name,
            owner=profile.get("user_name", "Unknown"),
            user_id=client_id,
            email=profile.get("email"),
            is_active=True,
            metadata={"exchanges": profile.get("exchanges", [])},
        )
