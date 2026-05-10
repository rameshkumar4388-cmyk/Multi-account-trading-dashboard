"""
Zerodha polling-based live quote feed.

Uses kite.ltp() on a background thread to keep prices current for all
subscribed symbols.  This is simpler than the full KiteTicker WebSocket
and sufficient for a 5-second refresh cycle.

Symbol format:
  Equity      →  NSE:{SYMBOL}   e.g. NSE:RELIANCE
  F&O         →  NFO:{SYMBOL}   e.g. NFO:NIFTY25JUNFUT
  Indices     →  NSE:NIFTY 50, NSE:NIFTY BANK  (Zerodha's canonical names)

The feed gracefully degrades: if ltp() fails for any reason the last
known price is kept and the error is logged but not raised.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from schemas.market_data import Tick

logger = logging.getLogger(__name__)

# Map plain symbol names to Zerodha's canonical index instrument strings
_INDEX_ALIASES: Dict[str, str] = {
    "NIFTY":     "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY":  "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY":"NSE:NIFTY MID SELECT",
    "SENSEX":    "BSE:SENSEX",
}

_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"

# Monthly F&O: two digits + three-letter month anywhere in the symbol (e.g. 25JUN)
_FNO_MONTHLY = re.compile(rf"\d{{2}}(?:{_MONTHS})")
# Weekly F&O: five consecutive digits (YYMDD expiry, e.g. 25619)
_FNO_WEEKLY  = re.compile(r"\d{5}")


def _to_instrument(symbol: str) -> str:
    """Convert a plain symbol to a Zerodha ltp() instrument string."""
    if symbol in _INDEX_ALIASES:
        return _INDEX_ALIASES[symbol]
    # Futures end with literal 'FUT'; check before the regex to keep it fast
    if symbol.endswith("FUT"):
        return f"NFO:{symbol}"
    if _FNO_MONTHLY.search(symbol) or _FNO_WEEKLY.search(symbol):
        return f"NFO:{symbol}"
    return f"NSE:{symbol}"


class ZerodhaQuoteFeed:
    """
    Polls kite.ltp() for subscribed symbols and emits Tick callbacks.

    Usage:
        feed = ZerodhaQuoteFeed(sessions={"acc1": kite_instance}, interval=5.0)
        feed.subscribe(["RELIANCE", "TCS", "NIFTY"])
        feed.add_callback(on_ticks)
        feed.start()
    """

    def __init__(self, sessions: Dict[str, object], interval: float = 5.0):
        """
        Args:
            sessions: Dict mapping account_id → KiteConnect instance.
                      Any active session is used for price fetching;
                      we only need one valid session.
            interval: Polling interval in seconds.
        """
        self._sessions = sessions          # account_id → KiteConnect
        self._interval = interval
        self._symbols: Set[str] = set()    # plain symbol names
        self._prices: Dict[str, float] = {}
        self._prev_prices: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[List[Tick]], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._running or not self._sessions:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ZerodhaQuoteFeed"
        )
        self._thread.start()
        logger.info(
            "ZerodhaQuoteFeed started (interval=%.0fs, sessions=%d)",
            self._interval, len(self._sessions),
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 1)

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, symbols: List[str]):
        with self._lock:
            for sym in symbols:
                self._symbols.add(sym)
        logger.debug("ZerodhaQuoteFeed: subscribed to %d symbols total", len(self._symbols))

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

    # ------------------------------------------------------------------
    # Background poll
    # ------------------------------------------------------------------

    def _active_kite(self):
        """Return any one available KiteConnect session."""
        for session in self._sessions.values():
            if session is not None:
                return session
        return None

    def _run(self):
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                logger.error("ZerodhaQuoteFeed poll error: %s", exc)
            time.sleep(self._interval)

    def _poll(self):
        kite = self._active_kite()
        if kite is None:
            return

        with self._lock:
            symbols = list(self._symbols)

        if not symbols:
            return

        # Build instrument strings; batch into groups of 500 (API limit)
        instruments = [_to_instrument(s) for s in symbols]
        instrument_map = dict(zip(instruments, symbols))  # instrument → plain symbol

        ticks: List[Tick] = []

        for i in range(0, len(instruments), 500):
            batch = instruments[i:i + 500]
            try:
                data = kite.ltp(batch)
            except Exception as exc:
                logger.warning("kite.ltp() failed for batch: %s", exc)
                continue

            with self._lock:
                for instrument, info in data.items():
                    plain = instrument_map.get(instrument, instrument.split(":")[-1])
                    ltp = float(info.get("last_price", 0))
                    if ltp <= 0:
                        continue

                    prev = self._prices.get(plain, ltp)
                    self._prev_prices[plain] = prev
                    self._prices[plain] = ltp

                    change = round(ltp - prev, 2)
                    change_pct = round((change / prev) * 100, 2) if prev else 0.0
                    ticks.append(Tick(symbol=plain, ltp=ltp, change=change, change_pct=change_pct))

        if ticks:
            for fn in self._callbacks:
                try:
                    fn(ticks)
                except Exception as exc:
                    logger.error("ZerodhaQuoteFeed callback error: %s", exc)

            logger.debug("ZerodhaQuoteFeed: updated %d prices", len(ticks))
