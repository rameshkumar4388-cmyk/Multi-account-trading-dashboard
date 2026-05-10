"""
Market data service — thin wrapper around MarketDataManager.

Exposes a clean interface for the UI/aggregation layers to access
live prices without depending on the underlying feed implementation.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from market_data.manager import MarketDataManager
from schemas.market_data import Tick

logger = logging.getLogger(__name__)


class MarketDataService:
    def __init__(self, settings):
        self._settings = settings
        self._manager = MarketDataManager(mode=settings.app_mode)
        self._initialized = False

    def initialize(self, symbols: List[str] = None):
        if not self._initialized:
            self._manager.initialize()
            self._initialized = True
        if symbols:
            self._manager.subscribe(symbols)

    def subscribe(self, symbols: List[str]):
        self._manager.subscribe(symbols)

    def get_ltp(self, symbol: str) -> Optional[float]:
        return self._manager.get_ltp(symbol)

    def get_change(self, symbol: str) -> float:
        return self._manager.get_change(symbol)

    def get_change_pct(self, symbol: str) -> float:
        return self._manager.get_change_pct(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        return self._manager.get_all_prices()

    def get_ticks(self, symbols: List[str]) -> List[Tick]:
        return self._manager.get_ticks(symbols)

    def attach_zerodha_feed(self, kite_sessions: dict, symbols: List[str] = None):
        """
        Attach a live Zerodha polling feed to the market data manager.

        Call this once after accounts have been authenticated in live mode.
        Safe to call with an empty sessions dict — does nothing in that case.

        Args:
            kite_sessions: Dict of account_id → KiteConnect from AccountService.
            symbols:       Optional list of symbols to subscribe immediately.
        """
        if self._settings.app_mode != "live":
            return
        if not kite_sessions:
            logger.warning("attach_zerodha_feed: no live sessions — skipping")
            return

        from brokers.zerodha.quote_feed import ZerodhaQuoteFeed
        feed = ZerodhaQuoteFeed(
            sessions=kite_sessions,
            interval=float(self._settings.market_data_refresh_interval),
        )
        if symbols:
            feed.subscribe(symbols)
        self._manager.attach_feed(feed)
        logger.info(
            "Zerodha quote feed attached (%d session(s), %d symbol(s))",
            len(kite_sessions), len(symbols or []),
        )

    def push_ticks(self, ticks: List[Tick]):
        """Called by live broker WebSocket handlers."""
        self._manager.push_ticks(ticks)

    def is_running(self) -> bool:
        feed = self._manager._feed
        return feed is not None and feed.is_running() if hasattr(feed, "is_running") else self._initialized

    def shutdown(self):
        self._manager.shutdown()
