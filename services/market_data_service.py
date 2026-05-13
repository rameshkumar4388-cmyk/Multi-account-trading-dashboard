"""
Market data service — synchronous, deterministic quote fetcher.

Replaces the background polling + subscription model with a simple
on-demand batch fetch via SP7086's KiteConnect session.

Data flow per render cycle (orchestrated by main.py):
  1. _build_quote_symbols() collects all needed symbols from cached data
  2. md_svc.refresh(symbols) calls kite.ohlc(all_instruments) once via SP7086
  3. All get_ltp()/get_change()/get_close() calls read from that snapshot

kite.ohlc() is used instead of kite.ltp() because it returns both
last_price AND ohlc.close (previous-day settlement price) in one call,
enabling local computation of change, change_pct, and positions day_pnl.

SP7086 is the ONLY account used for any quote/LTP/index call.
Other Zerodha accounts (VU5420, CL0502, FXU722, DA1898) never touch this.
No background threads. No subscriptions. No stale caches.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Zerodha canonical instrument strings for indices
_INDEX_ALIASES: Dict[str, str] = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "SENSEX":     "BSE:SENSEX",
}

_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
_FNO_MONTHLY = re.compile(rf"\d{{2}}(?:{_MONTHS})")
_FNO_WEEKLY  = re.compile(r"\d{5}")

_MOCK_BASE: Dict[str, float] = {
    "NIFTY": 24480.0, "BANKNIFTY": 52400.0, "FINNIFTY": 23100.0,
    "RELIANCE": 2847.5, "TCS": 3921.0, "HDFCBANK": 1678.45,
    "INFY": 1834.2, "WIPRO": 462.8, "ICICIBANK": 1198.6,
    "SBIN": 812.35, "BAJFINANCE": 7234.0, "AXISBANK": 1089.75,
    "KOTAKBANK": 1876.9, "ADANIENT": 2674.3, "MARUTI": 12850.0,
    "NIFTY25JUNFUT": 24520.0, "RELIANCE25JUNFUT": 2847.5,
    "NIFTY2561924500CE": 187.3, "BANKNIFTY2561944000PE": 278.5,
}


def _to_instrument(symbol: str) -> str:
    """Convert plain symbol name to Zerodha ltp() instrument string."""
    if symbol in _INDEX_ALIASES:
        return _INDEX_ALIASES[symbol]
    if symbol.endswith("FUT"):
        return f"NFO:{symbol}"
    if _FNO_MONTHLY.search(symbol) or _FNO_WEEKLY.search(symbol):
        return f"NFO:{symbol}"
    return f"NSE:{symbol}"


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
        Fetch quotes for all symbols via kite.ohlc() in one batched call via SP7086.
        ohlc() returns last_price + previous-day close, enabling local computation
        of change, change_pct, and positions day_pnl without relying on stale
        broker-cached fields. Batched in groups of 200 (Zerodha ohlc limit).
        """
        if not symbols:
            return

        if self._settings.app_mode != "live":
            self._mock_refresh(symbols)
            return

        kite = self._account_svc.get_market_data_kite_session()
        if kite is None:
            logger.warning(
                "MarketDataService.refresh: SP7086 session unavailable — "
                "quote snapshot not updated"
            )
            return

        instruments = [_to_instrument(s) for s in symbols]
        instrument_map = dict(zip(instruments, symbols))

        new_prices: Dict[str, float] = {}
        new_closes: Dict[str, float] = {}
        for i in range(0, len(instruments), 200):
            batch = instruments[i:i + 200]
            try:
                data = kite.ohlc(batch)
                for inst, info in data.items():
                    plain = instrument_map.get(inst, inst.split(":")[-1])
                    ltp   = float(info.get("last_price", 0))
                    close = float((info.get("ohlc") or {}).get("close", 0))
                    if ltp > 0:
                        new_prices[plain] = ltp
                    if close > 0:
                        new_closes[plain] = close
            except Exception as exc:
                logger.warning(
                    "kite.ohlc() batch [%d symbols] failed: %s", len(batch), exc
                )

        self._prices = new_prices
        self._closes = new_closes
        logger.debug(
            "MarketDataService.refresh: %d prices, %d closes fetched",
            len(new_prices), len(new_closes),
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
