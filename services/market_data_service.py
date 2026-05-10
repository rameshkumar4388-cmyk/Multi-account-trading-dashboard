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

    def push_ticks(self, ticks: List[Tick]):
        """Called by live broker WebSocket handlers."""
        self._manager.push_ticks(ticks)

    def is_running(self) -> bool:
        feed = self._manager._feed
        return feed is not None and feed.is_running() if hasattr(feed, "is_running") else self._initialized

    def shutdown(self):
        self._manager.shutdown()
