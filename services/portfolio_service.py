"""
Portfolio service — per-account data access with live price injection.

Fetches holdings and positions from broker adapters, then updates
LTP values from the shared MarketDataManager before returning data.
This keeps adapter calls (slow, rate-limited) separate from price
updates (fast, from WebSocket).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from schemas.account import AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)


class PortfolioService:
    def __init__(self, account_service, market_data_service):
        self._accounts = account_service
        self._md = market_data_service

        # In-memory cache: account_id → data + fetch timestamp
        self._holdings_cache: Dict[str, tuple] = {}   # (List[Holding], float)
        self._positions_cache: Dict[str, tuple] = {}
        self._margin_cache: Dict[str, tuple] = {}
        self._summary_cache: Dict[str, tuple] = {}

        self._ttl = 30.0  # seconds before re-fetching from broker

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _is_stale(self, cache: dict, key: str) -> bool:
        if key not in cache:
            return True
        _, fetched_at = cache[key]
        return (time.monotonic() - fetched_at) > self._ttl

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_holdings(self, account_id: str, force_refresh: bool = False) -> List[Holding]:
        if force_refresh or self._is_stale(self._holdings_cache, account_id):
            self._refresh_holdings(account_id)

        data, _ = self._holdings_cache.get(account_id, ([], 0.0))
        return self._inject_ltp_holdings(data)

    def get_positions(self, account_id: str, force_refresh: bool = False) -> List[Position]:
        if force_refresh or self._is_stale(self._positions_cache, account_id):
            self._refresh_positions(account_id)

        data, _ = self._positions_cache.get(account_id, ([], 0.0))
        return self._inject_ltp_positions(data)

    def get_margin(self, account_id: str, force_refresh: bool = False) -> Optional[MarginInfo]:
        if force_refresh or self._is_stale(self._margin_cache, account_id):
            self._refresh_margin(account_id)

        data, _ = self._margin_cache.get(account_id, (None, 0.0))
        return data

    def get_account_summary(self, account_id: str, force_refresh: bool = False) -> Optional[AccountSummary]:
        holdings = self.get_holdings(account_id, force_refresh)
        positions = self.get_positions(account_id, force_refresh)
        margin = self.get_margin(account_id, force_refresh)

        adapter = self._accounts.get_adapter(account_id)
        info = adapter.get_account_info(account_id) if adapter else None
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

        cfg = self._accounts._account_configs.get(account_id)
        display_name = cfg.display_name if cfg else info.display_name

        return AccountSummary(
            account_id=account_id,
            broker=info.broker,
            display_name=display_name,
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

    # ------------------------------------------------------------------
    # Internal refresh
    # ------------------------------------------------------------------

    def _refresh_holdings(self, account_id: str):
        adapter = self._accounts.get_adapter(account_id)
        if not adapter:
            return
        try:
            holdings = adapter.get_holdings(account_id)
            self._holdings_cache[account_id] = (holdings, time.monotonic())
        except Exception as exc:
            logger.error("Holdings refresh failed for %s: %s", account_id, exc)

    def _refresh_positions(self, account_id: str):
        adapter = self._accounts.get_adapter(account_id)
        if not adapter:
            return
        try:
            positions = adapter.get_positions(account_id)
            self._positions_cache[account_id] = (positions, time.monotonic())
        except Exception as exc:
            logger.error("Positions refresh failed for %s: %s", account_id, exc)

    def _refresh_margin(self, account_id: str):
        adapter = self._accounts.get_adapter(account_id)
        if not adapter:
            return
        try:
            margin = adapter.get_margin(account_id)
            self._margin_cache[account_id] = (margin, time.monotonic())
        except Exception as exc:
            logger.error("Margin refresh failed for %s: %s", account_id, exc)

    # ------------------------------------------------------------------
    # LTP injection
    # ------------------------------------------------------------------

    def _inject_ltp_holdings(self, holdings: List[Holding]) -> List[Holding]:
        for h in holdings:
            ltp = self._md.get_ltp(h.symbol)
            if ltp and ltp > 0:
                h.update_ltp(ltp)
                change = self._md.get_change(h.symbol)
                change_pct = self._md.get_change_pct(h.symbol)
                h.day_change = round(change * h.quantity, 2) if change else h.day_change
                h.day_change_pct = change_pct or h.day_change_pct
        return holdings

    def _inject_ltp_positions(self, positions: List[Position]) -> List[Position]:
        for p in positions:
            ltp = self._md.get_ltp(p.symbol)
            if ltp and ltp > 0:
                p.update_ltp(ltp)
        return positions
