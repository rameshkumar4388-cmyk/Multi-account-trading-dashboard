"""
Zerodha KiteConnect broker adapter.

Requires kiteconnect >= 5.0 and a valid access_token.
Falls back gracefully when kiteconnect is not installed.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)


class ZerodhaAdapter(BrokerAdapter):
    """
    Live Zerodha adapter using KiteConnect REST API.
    Supports multiple accounts via separate KiteConnect instances.
    """

    def __init__(self):
        self._sessions: Dict[str, object] = {}   # account_id → KiteConnect instance

    @property
    def broker_name(self) -> str:
        return "zerodha"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            logger.error("kiteconnect not installed. Run: pip install kiteconnect")
            return False

        api_key = credentials.get("api_key")
        access_token = credentials.get("access_token")
        if not api_key or not access_token:
            logger.error("Missing api_key or access_token for account %s", account_id)
            return False

        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            # Validate session with a lightweight call
            profile = kite.profile()
            self._sessions[account_id] = kite
            logger.info("Authenticated Zerodha account %s (%s)", account_id, profile.get("user_name"))
            return True
        except Exception as exc:
            logger.error("Zerodha authentication failed for %s: %s", account_id, exc)
            return False

    def is_session_valid(self, account_id: str) -> bool:
        return account_id in self._sessions

    def _kite(self, account_id: str):
        session = self._sessions.get(account_id)
        if not session:
            raise RuntimeError(f"No active session for account {account_id}. Call authenticate() first.")
        return session

    # ------------------------------------------------------------------
    # Data fetching — raw Kite data → normalized schemas
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
            logger.error("get_account_info failed for %s: %s", account_id, exc)
            return None

    def get_holdings(self, account_id: str) -> List[Holding]:
        try:
            raw = self._kite(account_id).holdings()
        except Exception as exc:
            logger.error("get_holdings failed for %s: %s", account_id, exc)
            return []

        holdings: List[Holding] = []
        for r in raw:
            qty = int(r.get("quantity", 0))
            if qty <= 0:
                continue
            avg = float(r.get("average_price", 0))
            ltp = float(r.get("last_price", 0))
            h = Holding(
                account_id=account_id,
                broker="zerodha",
                symbol=r.get("tradingsymbol", ""),
                exchange=r.get("exchange", "NSE"),
                isin=r.get("isin", ""),
                quantity=qty,
                avg_price=avg,
                ltp=ltp,
                sector=r.get("sector", "Unknown"),
                instrument_type="EQ",
                tradingsymbol=r.get("tradingsymbol", ""),
            )
            h.day_change = float(r.get("day_change", 0))
            h.day_change_pct = float(r.get("day_change_percentage", 0))
            holdings.append(h)

        return holdings

    def get_positions(self, account_id: str) -> List[Position]:
        try:
            raw_all = self._kite(account_id).positions()
        except Exception as exc:
            logger.error("get_positions failed for %s: %s", account_id, exc)
            return []

        positions: List[Position] = []
        net_positions = raw_all.get("net", [])

        for r in net_positions:
            qty = int(r.get("quantity", 0))
            if qty == 0:
                continue

            instrument_type = r.get("instrument_type", "EQ")
            pos = Position(
                account_id=account_id,
                broker="zerodha",
                symbol=r.get("tradingsymbol", ""),
                exchange=r.get("exchange", "NSE"),
                product=r.get("product", "MIS"),
                instrument_type=instrument_type,
                quantity=qty,
                avg_price=float(r.get("average_price", 0)),
                ltp=float(r.get("last_price", 0)),
                pnl=float(r.get("pnl", 0)),
                day_pnl=float(r.get("day_m2m", 0)),
                value=float(r.get("value", 0)),
                buy_quantity=int(r.get("buy_quantity", 0)),
                sell_quantity=int(r.get("sell_quantity", 0)),
                lot_size=int(r.get("lot_size", 1)) if instrument_type != "EQ" else 1,
                expiry=str(r.get("expiry", "")) or None,
                strike=float(r.get("strike", 0)) or None,
                underlying=r.get("tradingsymbol", ""),
                tradingsymbol=r.get("tradingsymbol", ""),
            )
            positions.append(pos)

        return positions

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        try:
            funds = self._kite(account_id).margins()
        except Exception as exc:
            logger.error("get_margin failed for %s: %s", account_id, exc)
            return None

        equity = funds.get("equity", {})
        available = equity.get("available", {})
        utilised = equity.get("utilised", {})

        return MarginInfo(
            account_id=account_id,
            broker="zerodha",
            available_cash=float(available.get("cash", 0)),
            used_margin=float(utilised.get("debits", 0)),
            span_margin=float(utilised.get("span", 0)),
            exposure_margin=float(utilised.get("exposure", 0)),
            total_collateral=float(available.get("collateral", 0)),
            net_available=float(available.get("live_balance", 0)),
            option_premium=float(utilised.get("option_premium", 0)),
        )

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        holdings = self.get_holdings(account_id)
        positions = self.get_positions(account_id)
        margin = self.get_margin(account_id)
        info = self.get_account_info(account_id)

        if not info:
            return None

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested = sum(h.invested_value for h in holdings)
        holdings_pnl = sum(h.pnl for h in holdings)
        positions_pnl = sum(p.pnl for p in positions)
        day_pnl = (
            sum(h.day_change * h.quantity for h in holdings)
            + sum(p.day_pnl for p in positions)
        )
        available_cash = margin.available_cash if margin else 0.0
        used_margin = margin.used_margin if margin else 0.0

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
            used_margin=used_margin,
            net_worth=round(total_holdings_value + available_cash, 2),
        )
