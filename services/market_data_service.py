"""
Market data service — synchronous, deterministic quote fetcher.

Data flow per render cycle (orchestrated by main.py):
  1. _build_quote_symbols() collects all needed symbols from cached data
  2. md_svc.refresh(symbols) calls FivePaisaAdapter.fetch_quotes_for_symbols()
  3. All get_ltp()/get_change()/get_close() calls read from that snapshot

fetch_quotes_for_symbols() resolves symbols via:
  - _scrip_cache (equity holdings, populated each cycle)
  - _scrip_master (full NSE cash scrip master, lazy-loaded once per process)
This covers equity holdings, stock-option underlyings, and indices
(NIFTY=999920000, BANKNIFTY=999920005, FINNIFTY=999920041).

No background threads. No subscriptions. No stale caches.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MOCK_BASE: Dict[str, float] = {
    "NIFTY": 24480.0, "BANKNIFTY": 52400.0, "FINNIFTY": 23100.0,
    "RELIANCE": 2847.5, "TCS": 3921.0, "HDFCBANK": 1678.45,
    "INFY": 1834.2, "WIPRO": 462.8, "ICICIBANK": 1198.6,
    "SBIN": 812.35, "BAJFINANCE": 7234.0, "AXISBANK": 1089.75,
    "KOTAKBANK": 1876.9, "ADANIENT": 2674.3, "MARUTI": 12850.0,
    "NIFTY25JUNFUT": 24520.0, "RELIANCE25JUNFUT": 2847.5,
    "NIFTY2561924500CE": 187.3, "BANKNIFTY2561944000PE": 278.5,
}


class MarketDataService:
    """
    Synchronous quote service. No background threads, no subscriptions.

    Call refresh(symbols) once per render cycle in main.py to populate
    the snapshot. All get_ltp() calls within the same render read from
    that single snapshot — every widget sees consistent prices.
    """

    def __init__(self, settings, account_svc):
        self._settings = settings
        self._account_svc = account_svc
        self._prices: Dict[str, float] = {}
        self._closes: Dict[str, float] = {}   # previous-day close from ohlc()

    # ------------------------------------------------------------------
    # Core refresh — called once per render cycle by main.py
    # ------------------------------------------------------------------

    def refresh(self, symbols: List[str]) -> None:
        """
        Fetch quotes for all symbols via 5paisa fetch_market_snapshot().
        Returns last_price + previous-day close, enabling local computation
        of change, change_pct, and positions day_pnl.
        Symbols are resolved via scrip cache (holdings) and scrip master fallback.
        """
        if not symbols:
            return

        logger.info("MarketDataService.refresh: requested symbols = %s", sorted(symbols))

        if self._settings.app_mode != "live":
            self._mock_refresh(symbols)
            return

        adapter = self._account_svc.get_market_data_fivepaisa_adapter()
        if adapter is None:
            logger.warning(
                "MarketDataService.refresh: no 5paisa adapter available — "
                "quote snapshot not updated"
            )
            return

        snapshot = adapter.fetch_quotes_for_symbols(symbols)

        new_prices: Dict[str, float] = {}
        new_closes: Dict[str, float] = {}
        for sym, data in snapshot.items():
            ltp   = float(data.get("ltp") or 0)
            close = float(data.get("close") or 0)
            if ltp > 0:
                new_prices[sym] = ltp
            if close > 0:
                new_closes[sym] = close

        self._prices = new_prices
        self._closes = new_closes
        logger.info(
            "MarketDataService.refresh: %d prices, %d closes via 5paisa snapshot "
            "(requested=%d)",
            len(new_prices), len(new_closes), len(symbols),
        )

    def _mock_refresh(self, symbols: List[str]) -> None:
        new_prices: Dict[str, float] = {}
        new_closes: Dict[str, float] = {}
        for sym in symbols:
            base = _MOCK_BASE.get(sym, 100.0)
            new_prices[sym] = round(base * (1 + random.gauss(0, 0.004)), 2)
            new_closes[sym] = base   # stable "yesterday's close" for consistent mock changes
        self._prices = new_prices
        self._closes = new_closes

    # ------------------------------------------------------------------
    # Price accessors — O(1) reads from snapshot
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def get_change(self, symbol: str) -> float:
        ltp   = self._prices.get(symbol)
        close = self._closes.get(symbol)
        if ltp and close:
            return round(ltp - close, 2)
        return 0.0

    def get_change_pct(self, symbol: str) -> float:
        ltp   = self._prices.get(symbol)
        close = self._closes.get(symbol)
        if ltp and close:
            return round((ltp - close) / close * 100, 2)
        return 0.0

    def get_close(self, symbol: str) -> Optional[float]:
        """Return previous-day close price for local day_pnl recomputation."""
        return self._closes.get(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        return dict(self._prices)

    def is_running(self) -> bool:
        return bool(self._prices)

    def get_ticks(self, symbols: List[str]) -> list:
        return []

    # ------------------------------------------------------------------
    # Compatibility stubs — interface unchanged; callers need no edits
    # ------------------------------------------------------------------

    def initialize(self, symbols: List[str] = None): pass
    def subscribe(self, symbols: List[str]): pass
    def attach_zerodha_feed(self, *args, **kwargs): pass
    def push_ticks(self, ticks): pass
    def shutdown(self): pass
