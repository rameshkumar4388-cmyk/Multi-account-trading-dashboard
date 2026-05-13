"""
Market data service — synchronous, deterministic quote fetcher.

Replaces the background polling + subscription model with a simple
on-demand batch fetch via SP7086's KiteConnect session.

Data flow per render cycle (orchestrated by main.py):
  1. _build_quote_symbols() collects all needed symbols from cached data
  2. md_svc.refresh(symbols) calls kite.ltp(all_instruments) once via SP7086
  3. All get_ltp() calls within the same render read from that snapshot

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

    # ------------------------------------------------------------------
    # Core refresh — called once per render cycle by main.py
    # ------------------------------------------------------------------

    def refresh(self, symbols: List[str]) -> None:
        """
        Fetch LTPs for all symbols in one batched kite.ltp() call via SP7086.
        Atomically replaces the internal snapshot; all get_ltp() calls then
        read from it. Batched in groups of 500 (Zerodha API limit).
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
        for i in range(0, len(instruments), 500):
            batch = instruments[i:i + 500]
            try:
                data = kite.ltp(batch)
                for inst, info in data.items():
                    plain = instrument_map.get(inst, inst.split(":")[-1])
                    ltp = float(info.get("last_price", 0))
                    if ltp > 0:
                        new_prices[plain] = ltp
            except Exception as exc:
                logger.warning(
                    "kite.ltp() batch [%d symbols] failed: %s", len(batch), exc
                )

        self._prices = new_prices
        logger.debug(
            "MarketDataService.refresh: %d / %d prices fetched",
            len(new_prices), len(symbols),
        )

    def _mock_refresh(self, symbols: List[str]) -> None:
        new_prices: Dict[str, float] = {}
        for sym in symbols:
            base = _MOCK_BASE.get(sym, 100.0)
            new_prices[sym] = round(base * (1 + random.gauss(0, 0.004)), 2)
        self._prices = new_prices

    # ------------------------------------------------------------------
    # Price accessors — O(1) reads from snapshot
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def get_change(self, symbol: str) -> float:
        # kite.ltp() returns last_price only; change is not available.
        # Holdings carry day_change from the holdings API; positions carry m2m.
        return 0.0

    def get_change_pct(self, symbol: str) -> float:
        return 0.0

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
