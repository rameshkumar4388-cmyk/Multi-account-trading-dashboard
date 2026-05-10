"""
Simulated live market data feed.

Uses a random-walk model to generate realistic tick-by-tick price movement
for all symbols in the universe. Prices drift around realistic Indian market
levels with configurable volatility.

This module runs in a background thread. Thread safety is enforced via
threading.Lock on the shared price store.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from schemas.market_data import Tick

logger = logging.getLogger(__name__)

# All base prices for the mock universe
_UNIVERSE_BASE: Dict[str, float] = {
    # Equities
    "RELIANCE":   2847.50, "TCS":        3921.00, "HDFCBANK":  1678.45,
    "INFY":       1834.20, "WIPRO":       462.80, "ICICIBANK": 1198.60,
    "SBIN":        812.35, "BAJFINANCE": 7234.00, "ASIANPAINT":3187.90,
    "MARUTI":    12850.00, "AXISBANK":   1089.75, "LT":        3612.40,
    "SUNPHARMA":  1821.55, "TATAMOTORS":  984.20, "ADANIENT":  2674.30,
    "KOTAKBANK":  1876.90, "HINDUNILVR": 2478.60, "ITC":        467.25,
    "POWERGRID":   329.80, "NTPC":        378.45,
    # Indices
    "NIFTY":     24480.00, "BANKNIFTY":  52400.00, "FINNIFTY":  23100.00,
    # Futures / Options underlying tracking
    "NIFTY25JUNFUT":      24520.00,
    "RELIANCE25JUNFUT":   2847.50,
    "NIFTY2561924500CE":   187.30,
    "BANKNIFTY2561944000PE": 278.50,
    "SBIN":               812.35,
}

# Per-symbol volatility override (annualized daily range %)
_VOLATILITY: Dict[str, float] = {
    "NIFTY2561924500CE":    0.035,
    "BANKNIFTY2561944000PE":0.038,
    "BANKNIFTY":            0.012,
    "BAJFINANCE":           0.020,
    "TATAMOTORS":           0.022,
    "ADANIENT":             0.025,
}
_DEFAULT_VOL = 0.008   # 0.8% per tick cycle


class MockFeed:
    """
    Thread-safe simulated price feed.

    Prices start at their universe base and perform a mean-reverting
    random walk each tick. Tick interval is configurable (default 0.5s).
    """

    def __init__(self, tick_interval: float = 0.5):
        self._tick_interval = tick_interval
        self._prices: Dict[str, float] = dict(_UNIVERSE_BASE)
        self._prev_close: Dict[str, float] = dict(_UNIVERSE_BASE)
        self._subscribers: Set[str] = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: List[Callable[[List[Tick]], None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="MockFeed"
        )
        self._thread.start()
        logger.info("MockFeed started (tick interval %.1fs)", self._tick_interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("MockFeed stopped")

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, symbols: List[str]):
        with self._lock:
            for sym in symbols:
                self._subscribers.add(sym)
                if sym not in self._prices and sym in _UNIVERSE_BASE:
                    self._prices[sym] = _UNIVERSE_BASE[sym]
                    self._prev_close[sym] = _UNIVERSE_BASE[sym]

    def unsubscribe(self, symbols: List[str]):
        with self._lock:
            for sym in symbols:
                self._subscribers.discard(sym)

    def add_callback(self, fn: Callable[[List[Tick]], None]):
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # Price access
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        with self._lock:
            return self._prices.get(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._prices)

    def get_ticks(self, symbols: List[str]) -> List[Tick]:
        ticks: List[Tick] = []
        with self._lock:
            for sym in symbols:
                ltp = self._prices.get(sym)
                if ltp is None:
                    continue
                prev = self._prev_close.get(sym, ltp)
                change = round(ltp - prev, 2)
                change_pct = round((change / prev) * 100, 2) if prev else 0.0
                ticks.append(Tick(
                    symbol=sym, ltp=ltp,
                    change=change, change_pct=change_pct,
                    timestamp=datetime.now(),
                ))
        return ticks

    # ------------------------------------------------------------------
    # Background simulation
    # ------------------------------------------------------------------

    def _run(self):
        while self._running:
            ticks = self._tick()
            if ticks and self._callbacks:
                for fn in self._callbacks:
                    try:
                        fn(ticks)
                    except Exception:
                        pass
            time.sleep(self._tick_interval)

    def _tick(self) -> List[Tick]:
        ticks: List[Tick] = []
        with self._lock:
            all_symbols = set(self._prices) | self._subscribers
            for sym in all_symbols:
                if sym not in self._prices:
                    base = _UNIVERSE_BASE.get(sym, 100.0)
                    self._prices[sym] = base
                    self._prev_close[sym] = base

                current = self._prices[sym]
                vol = _VOLATILITY.get(sym, _DEFAULT_VOL)
                base = _UNIVERSE_BASE.get(sym, current)

                # Mean-reverting random walk
                drift = (base - current) / base * 0.001  # gentle pull toward base
                shock = random.gauss(0, vol)
                new_price = max(current * (1 + drift + shock), 0.05)
                new_price = round(new_price, 2)

                self._prices[sym] = new_price
                prev = self._prev_close.get(sym, base)
                change = round(new_price - prev, 2)
                change_pct = round((change / prev) * 100, 2) if prev else 0.0

                ticks.append(Tick(
                    symbol=sym, ltp=new_price,
                    change=change, change_pct=change_pct,
                    timestamp=datetime.now(),
                ))

        return ticks
