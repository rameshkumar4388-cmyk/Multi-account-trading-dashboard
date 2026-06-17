"""
5paisa broker adapter — live implementation using py5paisa.

Authentication flow (token-based, no TOTP required):
    from py5paisa import FivePaisaClient
    cred = {
        "APP_NAME": ..., "APP_SOURCE": "27773",
        "USER_ID": ..., "USER_KEY": ...,
        "ENCRYPTION_KEY": ..., "PASSWORD": "dummy",
    }
    client = FivePaisaClient(cred=cred)
    client.set_access_token(access_token, client_code)

API response field reference (verified against py5paisa V3/V4 endpoints):

holdings()  →  body.Data  (list of dicts):
    NSECode          — NSE trading symbol (e.g. "RELIANCE"); "" for BSE-only scrips
    BSECode          — BSE numeric code
    ISIN             — ISIN code
    Price            — average buy price (cost basis per share)
    CurrentPrice     — current LTP
    CostValue        — total invested value (Price × Qty)
    CurrentValue     — current market value (CurrentPrice × Qty)
    Qty              — total quantity (free + T1 + pledged; analogous to Zerodha total_qty)
    DpQty            — DP settled / freely tradeable quantity
    EarmarkQty       — pledged / earmarked quantity
    BrokerName       — full company name
    Exchange         — "N" (NSE) or "B" (BSE)

positions()  →  body.NetPositionDetail  (list of dicts):
    Exch             — "N" (NSE) or "B" (BSE)
    ExchType         — "D" (derivatives/F&O), "C" (cash/equity)
    Symbol           — full trading symbol (e.g. "NIFTY25JUNFUT", "BANKNIFTY25JUN44000PE")
    NetQty           — net position quantity (+ long, − short)
    BuyAvgRate       — average buy price
    SellAvgRate      — average sell price (> 0 only when short or partial sell)
    LTP              — last traded price
    MTOM             — day mark-to-market P&L (unrealised, from session reference)
    BookedPL         — realised P&L (closed legs today)
    SLTP             — previous close / settlement price (used for day P&L calc)
    ExpDate          — expiry date in "/Date(ms)/" format (F&O only)
    StrikeRate       — strike price (options only; 0 for futures/equity)
    ScripType        — "CE", "PE" (options); "XX" (futures when ExchType="D");
                       "EQ"/"EQNRML" (equity when ExchType="C")
    OrderFor         — "I" (intraday/MIS), "D" (delivery/CNC), "H" (NRML hold)
    Multiplier       — lot size (1 for equity, 50/75/etc. for F&O)

margin()  →  body.EquityMargin  (list with ONE dict):
    AvailableBalance — usable cash balance
    BlockedAmount    — margin currently blocked (SPAN + exposure + option premium)
    Collateral       — pledged-holdings collateral value (post-haircut)
    TotalBalance     — AvailableBalance + BlockedAmount (approximate)
    Ledger           — ledger balance
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from brokers.zerodha.adapter import _NSE_SECTOR         # shared sector lookup
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)

# Regex to strip the underlying from an F&O symbol.
# Matches: NIFTY25JUNFUT → NIFTY, BANKNIFTY25JUN44000PE → BANKNIFTY
_FNO_UNDERLYING_RE = re.compile(r"^([A-Z&]+?)(\d{2}[A-Z]{3}|\d{5})")

_SNAPSHOT_BATCH_SIZE = 50  # 5paisa MarketSnapshot scrip-per-request cap

# 5paisa date format: "/Date(1750000000000)/" — milliseconds since epoch
_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _extract_underlying(symbol: str) -> str:
    m = _FNO_UNDERLYING_RE.match(symbol)
    return m.group(1) if m else symbol


def _parse_date(raw: str) -> Optional[str]:
    """Convert 5paisa "/Date(ms)/" to "YYYY-MM-DD", or return None."""
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if m:
        ts_ms = int(m.group(1))
        if ts_ms == 0:
            return None
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    # Already a plain date string
    return raw if raw.strip() else None


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return default


def _map_exchange(exch: str, exch_type: str) -> str:
    """Map 5paisa Exch/ExchType to human-readable exchange string."""
    if exch_type == "D":
        return "NFO" if exch == "N" else "BFO"
    return "NSE" if exch == "N" else "BSE"


def _map_instrument_type(scrip_type: str, exch_type: str) -> str:
    """Map 5paisa ScripType + ExchType to normalised instrument_type."""
    if scrip_type == "CE":
        return "CE"
    if scrip_type == "PE":
        return "PE"
    if exch_type == "D":
        return "FUT"   # "XX" in derivatives segment means futures
    return "EQ"


def _map_product(exch_type: str, order_for: str) -> str:
    """Map 5paisa ExchType + OrderFor to product code (MIS/CNC/NRML)."""
    if exch_type == "D":
        return "NRML"
    if order_for == "I":
        return "MIS"
    return "CNC"        # "D" (delivery) or "H" (hold)


class FivePaisaAdapter(BrokerAdapter):
    """
    Live 5paisa adapter.  One instance is created per account by AccountService.

    Authentication: supply APP_NAME / APP_SOURCE / USER_ID / USER_KEY /
    ENCRYPTION_KEY / PASSWORD credentials plus an ACCESS_TOKEN and CLIENT_CODE
    obtained from the 5paisa portal.  Call authenticate() on startup; the
    adapter holds the FivePaisaClient session for the lifetime of the process.
    """

    def __init__(self):
        self._client: Optional[object] = None       # FivePaisaClient instance
        self._client_code: str = ""
        self._account_id: str = ""
        self._credentials: dict = {}
        self._last_auth_error: Optional[str] = None
        self._scrip_cache: Dict[str, tuple] = {}    # symbol → (exch_char, scrip_code_str)
        self._scrip_master: Dict[str, str] = {}     # SymbolRoot → ScripCode (NSE cash, lazy)

    # ------------------------------------------------------------------
    # BrokerAdapter protocol
    # ------------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return "fivepaisa"

    @property
    def last_auth_error(self) -> Optional[str]:
        return self._last_auth_error

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        """
        Authenticate using a pre-obtained access_token + client_code.
        Calls margin() to verify the token is valid.
        """
        self._last_auth_error = None

        try:
            from py5paisa import FivePaisaClient
        except ImportError:
            self._last_auth_error = (
                "py5paisa not installed. Run: pip install py5paisa"
            )
            logger.error(self._last_auth_error)
            return False

        required = {
            "app_name":       credentials.get("app_name", ""),
            "app_source":     credentials.get("app_source", ""),
            "user_id":        credentials.get("user_id", ""),
            "user_key":       credentials.get("user_key", ""),
            "encryption_key": credentials.get("encryption_key", ""),
            "access_token":   credentials.get("access_token", ""),
            "client_code":    credentials.get("client_code", ""),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            self._last_auth_error = f"Missing credentials for '{account_id}': {missing}"
            logger.error(self._last_auth_error)
            return False

        try:
            cred = {
                "APP_NAME":       required["app_name"],
                "APP_SOURCE":     required["app_source"],
                "USER_ID":        required["user_id"],
                "USER_KEY":       required["user_key"],
                "ENCRYPTION_KEY": required["encryption_key"],
                "PASSWORD":       credentials.get("password", "dummy"),
            }
            client = FivePaisaClient(cred=cred)
            client.set_access_token(
                required["access_token"],
                required["client_code"],
            )

            # Verify token with a lightweight API call.
            # margin() returns None on auth failure; [] or [dict] on success.
            test = client.margin()
            if test is None:
                self._last_auth_error = (
                    f"5paisa token verification failed for '{account_id}'. "
                    "Check ACCESS_TOKEN and CLIENT_CODE."
                )
                logger.error(self._last_auth_error)
                return False

            self._client = client
            self._client_code = required["client_code"]
            self._account_id = account_id
            self._credentials = credentials
            logger.info(
                "5paisa authenticated '%s' (client_code=%s)",
                account_id, self._client_code,
            )
            return True

        except Exception as exc:
            self._last_auth_error = str(exc)
            logger.error("5paisa auth failed for '%s': %s", account_id, exc)
            return False

    def is_session_valid(self, account_id: str) -> bool:
        return self._client is not None and account_id == self._account_id

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        if not self.is_session_valid(account_id):
            return None
        display_name = (
            self._credentials.get("display_name")
            or f"5paisa ({self._client_code})"
        )
        return AccountInfo(
            account_id=account_id,
            broker="fivepaisa",
            display_name=display_name,
            owner=display_name,
            user_id=self._client_code,
            is_active=True,
            metadata={"client_code": self._client_code},
        )

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    def _fetch_market_snapshot(self, scrip_info: dict) -> dict:
        """
        Batch-fetch previous close + day change from 5paisa MarketSnapshot.

        scrip_info: {symbol → (exch_char, scrip_code_int)}
                    e.g. {"INTLCONV": ("N", 523648)}
        Returns:    {symbol → {"close": float, "change": float, "change_pct": float}}

        Uses 5paisa's own reference prices so InvIT/REIT unit distributions
        are handled consistently with the broker's own day P&L computation.
        """
        if not scrip_info or not self._client:
            return {}
        try:
            req_list = [
                {"Exchange": exch, "ExchangeType": "C", "ScripCode": sc}
                for _sym, (exch, sc) in scrip_info.items()
            ]
            # String-normalise keys so lookups work whether ScripCode comes
            # back as int (5606) or str ("5606") from the API.
            code_to_sym = {str(sc): sym for sym, (_exch, sc) in scrip_info.items()}

            total    = len(req_list)
            n_batches = (total + _SNAPSHOT_BATCH_SIZE - 1) // _SNAPSHOT_BATCH_SIZE
            logger.info(
                "5paisa _fetch_market_snapshot: %d scrips → %d batch(es) of ≤%d",
                total, n_batches, _SNAPSHOT_BATCH_SIZE,
            )

            result: Dict[str, dict] = {}
            for b_idx, b_start in enumerate(range(0, total, _SNAPSHOT_BATCH_SIZE), 1):
                batch = req_list[b_start : b_start + _SNAPSHOT_BATCH_SIZE]
                logger.info(
                    "5paisa _fetch_market_snapshot: batch %d/%d  scrips=%d",
                    b_idx, n_batches, len(batch),
                )
                raw = self._client.fetch_market_snapshot(batch)
                if not raw:
                    logger.warning(
                        "5paisa _fetch_market_snapshot: batch %d/%d empty response",
                        b_idx, n_batches,
                    )
                    continue

                # Detect API-level errors ("Scrip Limit Exceeded.", auth errors, etc.)
                if isinstance(raw, dict):
                    msg = (raw.get("Message") or "").strip()
                    if msg and msg.lower() not in ("", "success"):
                        logger.warning(
                            "5paisa _fetch_market_snapshot: batch %d/%d API error — %r  raw=%s",
                            b_idx, n_batches, msg, raw,
                        )
                        continue

                # fetch_market_snapshot returns res["body"] — a dict with "Data" key
                items = raw.get("Data", []) if isinstance(raw, dict) else (
                    raw if isinstance(raw, list) else []
                )

                for item in (items or []):
                    if not isinstance(item, dict):
                        continue
                    sc  = str(item.get("ScripCode") or item.get("Token") or "")
                    sym = code_to_sym.get(sc)
                    if not sym:
                        continue

                    # Verified field names from live 5paisa MarketSnapshot response:
                    #   PClose          — previous session close
                    #   NetChange       — day change (LTP − PClose)
                    #   LastTradedPrice — current LTP at snapshot call time
                    close    = _safe_float(item.get("PClose") or 0)
                    change   = _safe_float(item.get("NetChange") or 0)
                    ltp_snap = _safe_float(item.get("LastTradedPrice") or 0)

                    # Derive change from LTP − PClose when NetChange is absent/zero
                    if change == 0 and close > 0 and ltp_snap > 0:
                        change = round(ltp_snap - close, 4)

                    chg_pct = round(change / close * 100, 4) if close else 0.0

                    result[sym] = {
                        "close":      close,
                        "change":     change,
                        "change_pct": chg_pct,
                        "ltp":        ltp_snap,   # snapshot LTP — for sync-gap diagnosis
                    }

            logger.info(
                "5paisa _fetch_market_snapshot: %d / %d symbols resolved total",
                len(result), len(scrip_info),
            )
            return result

        except Exception as exc:
            logger.warning("5paisa _fetch_market_snapshot failed: %s", exc)
            return {}

    def _load_scrip_master(self) -> None:
        """
        Download and index the 5paisa scrip master (NSE cash segment only).
        Lazy-loaded once per process; cached in self._scrip_master.

        Bypasses py5paisa's get_scrips() which silently swallows errors and
        returns empty on failure. Makes the HTTP call directly so timeout and
        error details are visible in logs.
        """
        if self._scrip_master or not self._client:
            return
        try:
            import io
            import requests
            import pandas as pd

            URL = "https://images.5paisa.com/website/scripmaster-new-csv.csv"
            logger.info("5paisa _load_scrip_master: downloading from %s", URL)
            resp = requests.get(URL, timeout=60)
            resp.raise_for_status()

            records = pd.read_csv(io.StringIO(resp.text), low_memory=False)
            logger.info(
                "5paisa _load_scrip_master: %d rows downloaded, columns=%s",
                len(records), list(records.columns),
            )

            if records.empty:
                logger.warning("5paisa _load_scrip_master: CSV downloaded but is empty")
                return

            # Normalise column names — handle variations across API versions
            col_map = {c.strip().lower(): c for c in records.columns}
            exch_col     = col_map.get("exch") or col_map.get("exchange")
            exchtype_col = col_map.get("exchtype") or col_map.get("exchangetype")
            symroot_col  = col_map.get("symbolroot") or col_map.get("symbol") or col_map.get("name")
            sc_col       = col_map.get("scripcode") or col_map.get("code") or col_map.get("token")

            if not all([exch_col, exchtype_col, symroot_col, sc_col]):
                logger.warning(
                    "5paisa _load_scrip_master: expected columns not found — "
                    "exch=%s exchtype=%s symroot=%s sc=%s | available: %s",
                    exch_col, exchtype_col, symroot_col, sc_col,
                    list(records.columns),
                )
                return

            nse_cash = records[
                (records[exch_col] == "N") & (records[exchtype_col] == "C")
            ]
            master: Dict[str, str] = {}
            for _, row in nse_cash.iterrows():
                sym_root = str(row.get(symroot_col) or "").strip()
                sc       = str(row.get(sc_col) or "").strip()
                if sym_root and sc and sym_root not in master:
                    master[sym_root] = sc

            self._scrip_master = master
            logger.info(
                "5paisa _load_scrip_master: %d NSE cash symbols indexed "
                "(NIFTY=%s BANKNIFTY=%s)",
                len(master),
                master.get("NIFTY", "MISSING"),
                master.get("BANKNIFTY", "MISSING"),
            )
        except Exception as exc:
            logger.warning("5paisa _load_scrip_master failed: %s", exc, exc_info=True)

    def fetch_quotes_for_symbols(self, symbols: List[str]) -> Dict[str, dict]:
        """
        Fetch live quotes for the given symbol list via _fetch_market_snapshot().

        Resolution order per symbol:
          1. _scrip_cache  — equity holdings (populated by get_holdings each cycle)
          2. _scrip_master — full NSE cash scrip master (lazy-loaded once per process)

        Covers: equity holdings, stock-option underlyings not held in 5paisa,
        NIFTY (ScripCode 999920000), BANKNIFTY (999920005), FINNIFTY (999920041).
        Returns {symbol: {"ltp", "close", "change", "change_pct"}}.
        Unresolvable symbols are silently skipped and logged at DEBUG.
        """
        if not self._client or not symbols:
            return {}

        if not self._scrip_master:
            self._load_scrip_master()

        scrip_info: Dict[str, tuple] = {}
        unresolved: List[str] = []
        for sym in symbols:
            if sym in self._scrip_cache:
                scrip_info[sym] = self._scrip_cache[sym]
            elif sym in self._scrip_master:
                sc = self._scrip_master[sym]
                scrip_info[sym] = ("N", sc)
                self._scrip_cache[sym] = ("N", sc)  # warm for next cycle
            else:
                unresolved.append(sym)

        if unresolved:
            logger.debug(
                "fetch_quotes_for_symbols: %d unresolved (no scrip code): %s",
                len(unresolved), unresolved[:15],
            )

        if not scrip_info:
            logger.warning(
                "fetch_quotes_for_symbols: 0/%d symbols resolved — "
                "scrip master may not have loaded yet",
                len(symbols),
            )
            return {}

        logger.info(
            "fetch_quotes_for_symbols: requested=%d  resolved=%d  unresolved=%d",
            len(symbols), len(scrip_info), len(unresolved),
        )
        result = self._fetch_market_snapshot(scrip_info)
        logger.info(
            "fetch_quotes_for_symbols: snapshot returned %d/%d prices  unresolved=%d",
            len(result), len(symbols), len(unresolved),
        )
        return result

    def get_holdings(self, account_id: str) -> List[Holding]:
        if not self.is_session_valid(account_id):
            return []
        try:
            raw = self._client.holdings()
        except Exception as exc:
            logger.error("5paisa get_holdings failed for '%s': %s", account_id, exc)
            return []

        if not raw:
            return []

        # Surface all fields so unexpected keys are visible in logs
        first = raw[0] if isinstance(raw[0], dict) else {}
        logger.info("5paisa holdings payload keys (first row): %s", list(first.keys()))

        # ── DIAGNOSTIC: probe V4/NetPosition for broker-native BOD day P&L ────
        # holdings() confirmed: no DayGain / PreviousClose / day-P&L fields.
        # 5paisa docs: "positions for the day along with holdings as beginning
        # of the day" — V4/NetPosition (positions_day()) may carry MTOM /
        # PreviousClose / BODPositionPrice for CNC delivery holdings.
        # Logging full raw response to verify.  Remove after investigation.
        try:
            _netpos_raw = self._client.positions_day()
            if isinstance(_netpos_raw, dict):
                _netpos_keys = list(_netpos_raw.keys())
                _netpos_detail = _netpos_raw.get(
                    "NetPositionDetail",
                    _netpos_raw.get("Data", _netpos_raw.get("Positions", []))
                )
            elif isinstance(_netpos_raw, list):
                _netpos_keys  = ["<list>"]
                _netpos_detail = _netpos_raw
            else:
                _netpos_keys  = [str(type(_netpos_raw))]
                _netpos_detail = []
            logger.warning(
                "5PAISA NETPOS DIAG [%s] type=%s top_keys=%s items=%d",
                account_id, type(_netpos_raw).__name__,
                _netpos_keys, len(_netpos_detail or []),
            )
            for _np in (_netpos_detail or [])[:20]:   # cap at 20 rows
                if isinstance(_np, dict):
                    _np_sym = (_np.get("Symbol") or _np.get("Scrip") or "?").strip()
                    _np_fields = " | ".join(f"{k}={v!r}" for k, v in _np.items())
                    logger.warning(
                        "5PAISA NETPOS DIAG [%s] %s :: %s",
                        account_id, _np_sym, _np_fields,
                    )
        except Exception as _netpos_exc:
            logger.warning(
                "5PAISA NETPOS DIAG [%s] positions_day() failed: %s",
                account_id, _netpos_exc,
            )
        # ── END DIAGNOSTIC ───────────────────────────────────────────────────

        # Build snapshot identifiers from NseCode / BseCode (exchange-appropriate).
        # These are present in the holdings payload and accepted by fetch_market_snapshot
        # as ScripCode. Always build regardless of other available fields — snapshot
        # uses 5paisa's own reference prices (correct for InvITs/REITs with distributions).
        scrip_info: dict = {}
        for r in raw:
            sym  = (r.get("Symbol") or "").strip()
            exch = (r.get("Exch") or "N").strip()
            sc   = str(r.get("NseCode") if exch == "N" else r.get("BseCode") or "").strip()
            if sym and sc:
                scrip_info[sym] = (exch, sc)

        if scrip_info:
            logger.info("5paisa holdings: snapshot request for %d symbols", len(scrip_info))
            self._scrip_cache.update(scrip_info)   # warm cache for fetch_quotes_for_symbols
        else:
            logger.warning(
                "5paisa holdings: NseCode/BseCode absent from payload — "
                "day_change will be 0 for all holdings"
            )

        snapshot: dict = self._fetch_market_snapshot(scrip_info) if scrip_info else {}

        holdings: List[Holding] = []
        for r in raw:
            symbol = (r.get("Symbol") or "").strip()
            if not symbol:
                logger.warning("5paisa holding skipped — 'Symbol' missing: %s", r)
                continue

            qty = _safe_float(r.get("Quantity") or r.get("Qty"))
            if qty <= 0:
                logger.debug("5paisa holding skipped — zero Quantity for %s", symbol)
                continue

            avg_price    = _safe_float(r.get("AvgRate"))
            ltp          = _safe_float(r.get("CurrentPrice"))
            exchange_raw = (r.get("Exch") or "N").strip()
            exchange     = "NSE" if exchange_raw == "N" else "BSE"

            # ── Per-share day change: three sources in priority order ──────
            # All use 5paisa's own reference prices — critical for InvITs/REITs
            # where Zerodha's ohlc close diverges on ex-distribution days.
            day_change_per_share = 0.0
            day_change_pct       = 0.0

            day_gain   = r.get("DayGain")       # total position gain (all shares)
            prev_close = _safe_float(
                r.get("PreviousClose") or r.get("ClosePrice") or r.get("Close") or 0
            )
            raw_pct = (
                r.get("DayGainPercentage") or r.get("DayGainPct") or r.get("ChangePercent")
            )

            if day_gain is not None and qty > 0:
                # Priority 1: DayGain (total) ÷ qty → per-share
                day_change_per_share = round(_safe_float(day_gain) / qty, 4)
                day_change_pct = (
                    _safe_float(raw_pct) if raw_pct is not None
                    else (round(day_change_per_share / prev_close * 100, 4) if prev_close > 0 else 0.0)
                )
            elif prev_close > 0 and ltp > 0:
                # Priority 2: PreviousClose / ClosePrice in holdings row
                day_change_per_share = round(ltp - prev_close, 4)
                day_change_pct       = round(day_change_per_share / prev_close * 100, 4)
            elif symbol in snapshot:
                # Priority 3: MarketSnapshot (requires ScripCode)
                snap = snapshot[symbol]
                day_change_per_share = snap["change"]
                day_change_pct       = snap["change_pct"]
            else:
                logger.debug(
                    "5paisa holding %s: no previous-close source — day_change=0",
                    symbol,
                )

            # ── DIAGNOSTIC: LTP sync-gap + day P&L breakdown ─────────────────────
            _snap        = snapshot.get(symbol, {})
            _snap_pclose    = _snap.get("close",  None)
            _snap_netchange = _snap.get("change", None)
            _snap_ltp       = _snap.get("ltp",    None)   # LastTradedPrice from snapshot
            _ltp_delta      = round(ltp - _snap_ltp, 4) if (_snap_ltp and _snap_ltp > 0) else None
            _day_pnl_diag   = round(qty * day_change_per_share, 2)
            logger.warning(
                "5PAISA DAY-PNL DIAG [%s] symbol=%s qty=%.2f avg_price=%.4f "
                "holdings_CurrentPrice=%.4f snap_LastTradedPrice=%s ltp_delta=%s "
                "snap_PClose=%s snap_NetChange=%s "
                "day_change_used=%.4f day_pnl=%.2f",
                account_id, symbol, qty, avg_price,
                ltp,
                f"{_snap_ltp:.4f}"      if _snap_ltp      is not None else "n/a",
                f"{_ltp_delta:.4f}"     if _ltp_delta      is not None else "n/a",
                f"{_snap_pclose:.4f}"   if _snap_pclose    is not None else "n/a",
                f"{_snap_netchange:.4f}"if _snap_netchange is not None else "n/a",
                day_change_per_share, _day_pnl_diag,
            )
            # ── END DIAGNOSTIC ────────────────────────────────────────────────────

            sector = _NSE_SECTOR.get(symbol, "Other")

            h = Holding(
                account_id=account_id,
                broker="fivepaisa",
                symbol=symbol,
                exchange=exchange,
                isin="",
                quantity=qty,
                avg_price=avg_price,
                ltp=ltp,
                sector=sector,
                instrument_type="EQ",
                tradingsymbol=symbol,
            )
            h.day_change     = day_change_per_share
            h.day_change_pct = day_change_pct
            holdings.append(h)

        _total_day_pnl = round(sum(h.day_change * h.quantity for h in holdings), 2)
        logger.warning(
            "5PAISA DAY-PNL DIAG [%s] TOTAL holdings_day_pnl=%.2f holdings=%d",
            account_id, _total_day_pnl, len(holdings),
        )
        logger.info("5paisa get_holdings '%s': %d holdings", account_id, len(holdings))
        return holdings

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self, account_id: str) -> List[Position]:
        if not self.is_session_valid(account_id):
            return []
        try:
            raw = self._client.positions()
        except Exception as exc:
            logger.error("5paisa get_positions failed for '%s': %s", account_id, exc)
            return []

        if not raw:
            return []

        # Log the first row's keys so field names can be verified against live data
        if raw and isinstance(raw[0], dict):
            logger.info(
                "5paisa positions payload keys (first row): %s",
                list(raw[0].keys()),
            )

        positions: List[Position] = []
        for r in raw:
            net_qty = _safe_int(r.get("NetQty"))
            if net_qty == 0:
                continue

            exch      = (r.get("Exch") or "N").strip()
            exch_type = (r.get("ExchType") or "C").strip()
            scrip_type = (r.get("ScripType") or "EQ").strip()
            order_for  = (r.get("OrderFor") or "D").strip()
            symbol     = (r.get("Symbol") or "").strip()

            instrument_type = _map_instrument_type(scrip_type, exch_type)
            product         = _map_product(exch_type, order_for)
            exchange        = _map_exchange(exch, exch_type)
            underlying      = _extract_underlying(symbol)

            buy_avg  = _safe_float(r.get("BuyAvgRate"))
            sell_avg = _safe_float(r.get("SellAvgRate"))
            # avg_price = cost basis from the dominant side
            avg_price = buy_avg if net_qty > 0 else sell_avg

            ltp       = _safe_float(r.get("LTP"))
            mtom      = _safe_float(r.get("MTOM"))        # day M2M P&L
            booked_pl = _safe_float(r.get("BookedPL"))
            lot_size  = _safe_int(r.get("Multiplier"), 1) or 1

            # Unrealised P&L from cost basis
            if net_qty > 0:
                unrealised = round((ltp - avg_price) * abs(net_qty), 2)
            else:
                unrealised = round((avg_price - ltp) * abs(net_qty), 2)

            # F&O fields
            expiry_raw = r.get("ExpDate") or ""
            expiry     = _parse_date(expiry_raw)
            strike_raw = _safe_float(r.get("StrikeRate"))
            strike     = strike_raw if strike_raw > 0 else None

            buy_qty  = _safe_int(r.get("BuyQty"))
            sell_qty = _safe_int(r.get("SellQty"))
            value    = round(abs(net_qty) * ltp, 2)

            pos = Position(
                account_id=account_id,
                broker="fivepaisa",
                symbol=symbol,
                exchange=exchange,
                product=product,
                instrument_type=instrument_type,
                quantity=net_qty,
                avg_price=avg_price,
                ltp=ltp,
                pnl=unrealised,
                day_pnl=mtom,           # session M2M — same semantics as Zerodha's m2m
                value=value,
                buy_quantity=buy_qty,
                sell_quantity=sell_qty,
                lot_size=lot_size,
                expiry=expiry,
                strike=strike,
                underlying=underlying,
                tradingsymbol=symbol,
            )
            positions.append(pos)

            logger.debug(
                "5paisa position: %s type=%s qty=%d avg=%.2f ltp=%.2f "
                "unrealised=%.2f mtom=%.2f underlying=%s",
                symbol, instrument_type, net_qty, avg_price, ltp,
                unrealised, mtom, underlying,
            )

        logger.info("5paisa get_positions '%s': %d open positions", account_id, len(positions))
        return positions

    # ------------------------------------------------------------------
    # Margin
    # ------------------------------------------------------------------

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        if not self.is_session_valid(account_id):
            return None
        try:
            raw = self._client.margin()
        except Exception as exc:
            logger.error("5paisa get_margin '%s' API call failed: %s", account_id, exc)
            return None

        if not raw:
            logger.warning("5paisa get_margin '%s': empty EquityMargin response", account_id)
            return MarginInfo(account_id=account_id, broker="fivepaisa")

        # margin() returns a list; take the first (and usually only) element.
        # Confirmed field names from live py5paisa response:
        #   Ledgerbalance, NetAvailableMargin, MarginUtilized,
        #   GrossHoldingValue, DPFreeStockValue, DerivativeMargin, OptionsPremium
        m = raw[0] if isinstance(raw, list) else raw

        if not isinstance(m, dict):
            logger.error(
                "5paisa get_margin '%s': unexpected payload type %s — raw=%s",
                account_id, type(m).__name__, raw,
            )
            return MarginInfo(account_id=account_id, broker="fivepaisa")

        available     = _safe_float(m.get("Ledgerbalance"))
        net_available = _safe_float(m.get("NetAvailableMargin"))
        blocked       = _safe_float(m.get("MarginUtilized"))
        # Pledged collateral = total DP value minus the free (unpledged) portion.
        # GrossHoldingValue = market value of ALL DP holdings (free + pledged).
        # DPFreeStockValue  = market value of unpledged holdings only.
        # Difference = value of pledged (collateralized) holdings.
        # When nothing is pledged both values are equal → collateral = 0.
        gross_holding  = _safe_float(m.get("GrossHoldingValue"))
        dp_free        = _safe_float(m.get("DPFreeStockValue"))
        collateral     = max(round(gross_holding - dp_free, 2), 0.0)
        deriv_margin   = _safe_float(m.get("DerivativeMargin"))
        option_premium = _safe_float(m.get("OptionsPremium"))

        logger.info(
            "5paisa get_margin '%s': ledger=%.2f net_avail=%.2f "
            "margin_used=%.2f gross=%.2f dp_free=%.2f collateral=%.2f "
            "deriv=%.2f opt_prem=%.2f",
            account_id, available, net_available,
            blocked, gross_holding, dp_free, collateral,
            deriv_margin, option_premium,
        )

        return MarginInfo(
            account_id=account_id,
            broker="fivepaisa",
            available_cash=available,
            net_available=net_available,
            used_margin=blocked,
            total_collateral=collateral,
            span_margin=deriv_margin,
            option_premium=option_premium,
        )

    # ------------------------------------------------------------------
    # Account summary (delegates to individual methods)
    # ------------------------------------------------------------------

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        """Compute AccountSummary from live API data. Used by the adapter directly
        only when portfolio_service is not involved (e.g., debug calls)."""
        info = self.get_account_info(account_id)
        if not info:
            return None

        holdings  = self.get_holdings(account_id)
        positions = self.get_positions(account_id)
        margin    = self.get_margin(account_id)

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested       = sum(h.invested_value for h in holdings)
        holdings_pnl         = sum(h.pnl for h in holdings)
        positions_pnl        = sum(p.pnl for p in positions)
        holdings_day_pnl     = sum(h.day_change * h.quantity for h in holdings)
        positions_day_pnl    = sum(p.day_pnl for p in positions)
        day_pnl              = round(holdings_day_pnl + positions_day_pnl, 2)

        available_cash   = margin.available_cash   if margin else 0.0
        net_available    = margin.net_available    if margin else 0.0
        used_margin      = margin.used_margin      if margin else 0.0
        total_collateral = margin.total_collateral if margin else 0.0

        net_worth = round(total_holdings_value + available_cash + positions_pnl, 2)

        return AccountSummary(
            account_id=account_id,
            broker="fivepaisa",
            display_name=info.display_name,
            owner=info.owner,
            total_holdings_value=round(total_holdings_value, 2),
            total_invested_value=round(total_invested, 2),
            holdings_pnl=round(holdings_pnl, 2),
            holdings_pnl_pct=(
                round((holdings_pnl / total_invested) * 100, 2) if total_invested else 0.0
            ),
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
    # Subscribed symbols (for MD service symbol set building)
    # ------------------------------------------------------------------

    def get_subscribed_symbols(self, account_id: str) -> List[str]:
        """Return symbols from live holdings + positions for quote subscription."""
        symbols: List[str] = []
        for h in self.get_holdings(account_id):
            if h.instrument_type != "MF":
                symbols.append(h.symbol)
        for p in self.get_positions(account_id):
            symbols.append(p.symbol)
            if p.underlying and p.underlying != p.symbol:
                symbols.append(p.underlying)
        return list(dict.fromkeys(symbols))
