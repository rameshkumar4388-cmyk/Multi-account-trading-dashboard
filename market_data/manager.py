"""
Centralized market data manager.

Single source of truth for all live prices across the dashboard.
Responsibilities:
  - Aggregate symbol subscriptions from all accounts (avoid duplicates)
  - Route subscriptions to the appropriate feed (mock or live WebSocket)
  - Provide O(1) price lookup to any service layer consumer
  - Push price updates to registered callbacks
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, List, Optional

from schemas.market_data import Tick

logger = logging.getLogger(__name__)


class MarketDataManager:
    """
    Thread-safe centralized price store.
    Wraps either MockFeed or a live WebSocket feed.
    """

    def __init__(self, mode: str = "mock"):
        self._mode = mode
        self._feed = None
        self._prices: Dict[str, float] = {}
        self._changes: Dict[str, float] = {}
        self._changes_pct: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[List[Tick]], None]] = []
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        if self._mode == "mock":
            from market_data.mock_feed import MockFeed
            self._feed = MockFeed(tick_interval=0.5)
            self._feed.add_callback(self._on_ticks)
            self._feed.start()
        else:
            self._init_live_feed()
        self._initialized = True
        logger.info("MarketDataManager initialized in '%s' mode", self._mode)

    def _init_live_feed(self):
        """
        Placeholder for live WebSocket feed initialization.
        In Zerodha live mode, initialize KiteTicker here.
        Each broker adapter can register its own WebSocket handler
        and call push_ticks() to feed prices into the shared store.
        """
        logger.info("Live feed mode: waiting for broker WebSocket connections")

    def shutdown(self):
        if self._feed and hasattr(self._feed, "stop"):
            self._feed.stop()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, symbols: List[str]):
        """Subscribe to live updates for the given symbol list."""
        if not symbols:
            return
        if self._feed and hasattr(self._feed, "subscribe"):
            self._feed.subscribe(symbols)
        logger.debug("Subscribed to %d symbols", len(symbols))

    def unsubscribe(self, symbols: List[str]):
        if self._feed and hasattr(self._feed, "unsubscribe"):
            self._feed.unsubscribe(symbols)

    def add_callback(self, fn: Callable[[List[Tick]], None]):
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # External price push (for live broker WebSocket handlers)
    # ------------------------------------------------------------------

    def push_ticks(self, ticks: List[Tick]):
        """Called by live broker WebSocket handlers to push price updates."""
        self._on_ticks(ticks)

    # ------------------------------------------------------------------
    # Price access
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        with self._lock:
            if self._mode == "mock" and self._feed:
                return self._feed.get_ltp(symbol)
            return self._prices.get(symbol)

    def get_change(self, symbol: str) -> float:
        with self._lock:
            return self._changes.get(symbol, 0.0)

    def get_change_pct(self, symbol: str) -> float:
        with self._lock:
            return self._changes_pct.get(symbol, 0.0)

    def get_all_prices(self) -> Dict[str, float]:
        if self._mode == "mock" and self._feed:
            return self._feed.get_all_prices()
        with self._lock:
            return dict(self._prices)

    def get_ticks(self, symbols: List[str]) -> List[Tick]:
        if self._mode == "mock" and self._feed:
            return self._feed.get_ticks(symbols)
        ticks: List[Tick] = []
        with self._lock:
            for sym in symbols:
                ltp = self._prices.get(sym)
                if ltp is not None:
                    ticks.append(Tick(
                        symbol=sym,
                        ltp=ltp,
                        change=self._changes.get(sym, 0.0),
                        change_pct=self._changes_pct.get(sym, 0.0),
                    ))
        return ticks

    # ------------------------------------------------------------------
    # Internal tick handler
    # ------------------------------------------------------------------

    def _on_ticks(self, ticks: List[Tick]):
        with self._lock:
            for tick in ticks:
                self._prices[tick.symbol] = tick.ltp
                self._changes[tick.symbol] = tick.change
                self._changes_pct[tick.symbol] = tick.change_pct
        for fn in self._callbacks:
            try:
                fn(ticks)
            except Exception:
                pass
