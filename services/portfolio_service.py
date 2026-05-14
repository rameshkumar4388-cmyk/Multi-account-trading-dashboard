"""
Portfolio service — per-account data access with live price injection.

Fetches holdings and positions from broker adapters, then overlays
the latest LTP from the MarketDataService before returning data.

day_change semantics (critical):
  h.day_change is the PER-SHARE price change vs. yesterday's close (₹).
  Day P&L for a holding = h.day_change * h.quantity.
  The inject step must NOT multiply by quantity — that happens in the
  summary aggregation step only.
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

        self._holdings_cache:  Dict[str, tuple] = {}   # account_id → (data, fetched_at)
        self._positions_cache: Dict[str, tuple] = {}
        self._margin_cache:    Dict[str, tuple] = {}

        self._ttl = 30.0  # seconds before re-fetching from broker

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _is_stale(self, cache: dict, key: str) -> bool:
        if key not in cache:
            return True
        _, fetched_at = cache[key]
        return (time.monotonic() - fetched_at) > self._ttl

    def invalidate(self, account_id: str):
        """Force-expire all cached data for an account (e.g. after token refresh)."""
        for cache in (self._holdings_cache, self._positions_cache, self._margin_cache):
            cache.pop(account_id, None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_holdings(self, account_id: str, force_refresh: bool = False) -> List[Holding]:
        if force_refresh or self._is_stale(self._holdings_cache, account_id):
            self._refresh_holdings(account_id)
        data, _ = self._holdings_cache.get(account_id, ([], 0.0))
        # Deep-copy so LTP injection never mutates the cached Holding objects.
        # Without this, repeated calls within the TTL window would corrupt day_change
        # by overwriting it with quote-feed values on every render.
        import copy
        return self._inject_ltp_holdings([copy.copy(h) for h in data])

    def get_positions(self, account_id: str, force_refresh: bool = False) -> List[Position]:
        if force_refresh or self._is_stale(self._positions_cache, account_id):
            self._refresh_positions(account_id)
        data, _ = self._positions_cache.get(account_id, ([], 0.0))
        import copy
        return self._inject_ltp_positions([copy.copy(p) for p in data])

    def get_margin(self, account_id: str, force_refresh: bool = False) -> Optional[MarginInfo]:
        if force_refresh or self._is_stale(self._margin_cache, account_id):
            self._refresh_margin(account_id)
        data, _ = self._margin_cache.get(account_id, (None, 0.0))
        return data

    def get_account_summary(self, account_id: str, force_refresh: bool = False) -> Optional[AccountSummary]:
        holdings  = self.get_holdings(account_id, force_refresh)
        positions = self.get_positions(account_id, force_refresh)
        margin    = self.get_margin(account_id, force_refresh)

        adapter = self._accounts.get_adapter(account_id)
        info = adapter.get_account_info(account_id) if adapter else None
        if not info:
            return None

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested       = sum(h.invested_value for h in holdings)
        holdings_pnl         = sum(h.pnl for h in holdings)
        positions_pnl        = sum(p.pnl for p in positions)

        # day_change is per-share — multiply by quantity to get day value change
        holdings_day_pnl  = sum(h.day_change * h.quantity for h in holdings)
        positions_day_pnl = sum(p.day_pnl for p in positions)
        day_pnl           = round(holdings_day_pnl + positions_day_pnl, 2)

        available_cash   = margin.available_cash   if margin else 0.0
        net_available    = margin.net_available    if margin else 0.0
        used_margin      = margin.used_margin      if margin else 0.0
        total_collateral = margin.total_collateral if margin else 0.0

        cfg = self._accounts._account_configs.get(account_id)
        # info.display_name is "Zerodha (SP7086)" — derived from API profile at auth time.
        # cfg.display_name is also updated after auth; use info as primary source.
        display_name = (info.display_name if info else None) or (cfg.display_name if cfg else account_id)

        # Net worth = holdings market value + cash + open positions MTM P&L
        net_worth = round(total_holdings_value + available_cash + positions_pnl, 2)

        logger.debug(
            "AccountSummary '%s': %d holdings val=%.2f pnl=%.2f | "
            "%d positions pnl=%.2f | day_pnl=%.2f | "
            "cash=%.2f net_avail=%.2f collateral=%.2f net_worth=%.2f",
            account_id, len(holdings), total_holdings_value, holdings_pnl,
            len(positions), positions_pnl, day_pnl,
            available_cash, net_available, total_collateral, net_worth,
        )

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
            day_pnl=day_pnl,
            holdings_day_pnl=round(holdings_day_pnl, 2),
            available_cash=available_cash,
            net_available=net_available,
            used_margin=used_margin,
            total_collateral=total_collateral,
            net_worth=net_worth,
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
    # LTP injection — overlays fresh prices from market data service
    # ------------------------------------------------------------------

    def _inject_ltp_holdings(self, holdings: List[Holding]) -> List[Holding]:
        for h in holdings:
            if h.instrument_type == "MF":
                continue   # MF NAVs are EOD-only; no live quote injection
            ltp = self._md.get_ltp(h.symbol)
            if ltp and ltp > 0:
                h.update_ltp(ltp)
                # day_change must stay as PER-SHARE price change (not total value).
                # It will be multiplied by quantity in the summary aggregation.
                fresh_change     = self._md.get_change(h.symbol)
                fresh_change_pct = self._md.get_change_pct(h.symbol)
                # Only inject ohlc-based day_change for brokers that don't
                # provide it natively in their holdings API.  5paisa holdings
                # carry no broker-computed day_change; the ohlc close from
                # SP7086 can diverge badly for instruments with recent corporate
                # actions (e.g. InvIT/REIT unit distributions show as artificial
                # losses). Leaving day_change at 0 is honest; injecting a wrong
                # value produces a wildly incorrect day P&L.
                # Zerodha: broker-native day_change from holdings API is canonical.
                # 5paisa:  adapter provides it via MarketSnapshot; ohlc would diverge.
                # Others:  inject from ohlc (no broker-provided day_change).
                if fresh_change and h.broker not in ("zerodha", "fivepaisa"):
                    h.day_change = fresh_change          # ← per-share only, no × quantity
                if fresh_change_pct and h.broker not in ("zerodha", "fivepaisa"):
                    h.day_change_pct = fresh_change_pct
        return holdings

    def _inject_ltp_positions(self, positions: List[Position]) -> List[Position]:
        for p in positions:
            ltp = self._md.get_ltp(p.symbol)
            if ltp and ltp > 0:
                p.update_ltp(ltp)
                # day_pnl for NRML/CNC: Zerodha's broker-native m2m is canonical.
                # SP7086 ohlc.close differs from Zerodha's internal settlement
                # reference, causing persistent drift vs the Kite app.
                # MIS formula is (ltp − avg_price) × qty — identical regardless
                # of source, so fresh ltp is used for both brokers.
                if p.product == "MIS":
                    p.day_pnl = round((ltp - p.avg_price) * p.quantity, 2)
                elif p.broker != "zerodha":
                    close = self._md.get_close(p.symbol)
                    if close and close > 0:
                        p.day_pnl = round((ltp - close) * p.quantity, 2)
        return positions
