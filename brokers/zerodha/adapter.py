"""
Zerodha KiteConnect broker adapter.

Requires kiteconnect >= 5.0 and a valid access_token.

Field-mapping reference (verified against Zerodha KiteConnect API):

holdings() response keys used here:
  tradingsymbol, exchange, isin, instrument_token
  quantity            — free settled qty (EXCLUDES T1, auth-pending, and pledged)
  t1_quantity         — T+1 unsettled (bought today/yesterday, settling tomorrow)
  authorised_quantity — pledge initiated but CDSL depository OTP not yet done
                        (shares are frozen/locked, NOT in quantity or used_quantity)
  used_quantity       — pledge fully authorised, margin is live
  average_price       — cost basis per share
  last_price          — current LTP
  close_price         — previous session close (for day-change calc)
  day_change          — per-share price change vs. close_price
  day_change_percentage
  pnl                 — broker-computed unrealized P&L
  collateral_type     — "margin" if pledged, "" otherwise

  TOTAL OWNED = quantity + t1_quantity + authorised_quantity + used_quantity
  Missing authorised_quantity causes mid-pledge holdings to show zero quantity.

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
    """Return the underlying asset name from a Zerodha trading symbol."""
    if instrument_type == "EQ":
        return tradingsymbol
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
            logger.info(
                "Authenticated Zerodha account '%s' as %s",
                account_id, profile.get("user_name", "unknown"),
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
        try:
            raw = self._kite(account_id).holdings()
        except Exception as exc:
            logger.error("get_holdings failed for '%s': %s", account_id, exc)
            return []

        # Permanent marker — visible in logs on every real call.
        # If you see "v4-field" in logs the new code is active.
        # If you see nothing, the process is running stale bytecode.
        logger.info(
            "get_holdings '%s': %d raw rows [qty-formula=v4-field: "
            "free+t1+auth+pledged]",
            account_id, len(raw),
        )

        holdings: List[Holding] = []
        for r in raw:
            # ── Quantity: the Zerodha pledge lifecycle has four states ─
            #
            # quantity           = free settled shares (can sell today)
            # t1_quantity        = recently purchased, T+1 settlement pending
            # authorised_quantity= pledge initiated but CDSL OTP not yet done
            # used_quantity      = pledge fully authorised, margin is live
            #
            # All four belong to the user and must be included in portfolio
            # valuation.  Omitting authorised_quantity causes holdings that
            # are mid-pledge-authorisation to silently drop from net worth.
            free_qty   = int(r.get("quantity", 0)            or 0)
            t1_qty     = int(r.get("t1_quantity", 0)         or 0)
            auth_qty   = int(r.get("authorised_quantity", 0) or 0)
            pledged_qty= int(r.get("used_quantity", 0)       or 0)
            total_qty  = free_qty + t1_qty + auth_qty + pledged_qty

            if total_qty <= 0:
                logger.debug(
                    "Skipping %s: free=%d t1=%d auth=%d pledged=%d (all zero)",
                    r.get("tradingsymbol"), free_qty, t1_qty, auth_qty, pledged_qty,
                )
                continue

            avg_price   = float(r.get("average_price", 0))
            last_price  = float(r.get("last_price", 0))
            close_price = float(r.get("close_price", 0))

            # day_change from Zerodha is per-share price change vs. close_price
            day_change     = float(r.get("day_change", 0))
            day_change_pct = float(r.get("day_change_percentage", 0))

            # Fallback: compute day_change from close_price if API returns 0
            if day_change == 0 and close_price > 0 and last_price > 0:
                day_change = round(last_price - close_price, 2)
                if close_price > 0:
                    day_change_pct = round((day_change / close_price) * 100, 2)

            is_pledged      = bool(auth_qty > 0 or pledged_qty > 0)
            collateral_type = r.get("collateral_type", "")

            h = Holding(
                account_id=account_id,
                broker="zerodha",
                symbol=r.get("tradingsymbol", ""),
                exchange=r.get("exchange", "NSE"),
                isin=r.get("isin", ""),
                quantity=total_qty,
                avg_price=avg_price,
                ltp=last_price,
                sector=r.get("sector", "Unknown"),
                instrument_type="EQ",
                tradingsymbol=r.get("tradingsymbol", ""),
            )
            h.day_change     = day_change      # per-share price change (₹)
            h.day_change_pct = day_change_pct  # %

            logger.debug(
                "Holding: %s total=%d (free=%d t1=%d auth=%d pledged=%d) "
                "avg=%.2f ltp=%.2f day_chg=%.2f pnl=%.2f pledged=%s",
                r.get("tradingsymbol"), total_qty,
                free_qty, t1_qty, auth_qty, pledged_qty,
                avg_price, last_price, day_change, h.pnl, collateral_type or "no",
            )
            holdings.append(h)

        logger.info(
            "get_holdings '%s': %d holdings loaded (total qty across all)",
            account_id, len(holdings),
        )
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

        # Pure cash sitting in the account (no collateral or intraday credits)
        cash = float(available.get("cash", 0))

        # Collateral from pledged holdings (after haircut approved by Zerodha)
        collateral = float(available.get("collateral", 0))

        # Total available for trading = cash + collateral - blocked margin
        # live_balance is Zerodha's pre-computed value of this
        live_balance = float(available.get("live_balance", 0))

        # Margin currently blocked
        debits           = float(utilised.get("debits", 0))
        span             = float(utilised.get("span", 0))
        exposure         = float(utilised.get("exposure", 0))
        option_premium   = float(utilised.get("option_premium", 0))

        logger.debug(
            "get_margin '%s': cash=%.2f collateral=%.2f live_balance=%.2f debits=%.2f",
            account_id, cash, collateral, live_balance, debits,
        )

        return MarginInfo(
            account_id=account_id,
            broker="zerodha",
            available_cash=cash,
            net_available=live_balance,
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
        day_pnl = (
            sum(h.day_change * h.quantity for h in holdings)
            + sum(p.day_pnl for p in positions)
        )
        available_cash   = margin.available_cash   if margin else 0.0
        net_available    = margin.net_available    if margin else 0.0
        used_margin      = margin.used_margin      if margin else 0.0
        total_collateral = margin.total_collateral if margin else 0.0

        # Net worth = market value of all holdings + pure cash balance
        # Collateral is NOT added separately (pledged holdings are already in holdings_value)
        net_worth = round(total_holdings_value + available_cash, 2)

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
        try:
            profile = self._kite(account_id).profile()
            return AccountInfo(
                account_id=account_id,
                broker="zerodha",
                display_name=profile.get("user_name", account_id),
                owner=profile.get("user_name", "Unknown"),
                user_id=profile.get("user_id"),
                email=profile.get("email"),
                is_active=True,
                metadata={"exchanges": profile.get("exchanges", [])},
            )
        except Exception as exc:
            logger.error("get_account_info failed for '%s': %s", account_id, exc)
            return None
