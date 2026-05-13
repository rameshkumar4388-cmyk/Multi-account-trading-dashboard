"""
Mock broker adapter — generates realistic Indian market data for development and demo.

Three pre-configured mock accounts:
  - zerodha_primary   : long-term equity portfolio
  - zerodha_trading   : active F&O + equity trading
  - groww_invest      : SIP/MF-style equity investments
"""
from __future__ import annotations

import random
from datetime import datetime, date
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position


# ---------------------------------------------------------------------------
# Static seed data — prices will be overridden by MarketDataService at runtime
# ---------------------------------------------------------------------------

_EQUITY_UNIVERSE = {
    "RELIANCE":  {"isin": "INE002A01018", "sector": "Energy",         "base": 2847.50},
    "TCS":       {"isin": "INE467B01029", "sector": "IT",             "base": 3921.00},
    "HDFCBANK":  {"isin": "INE040A01034", "sector": "Banking",        "base": 1678.45},
    "INFY":      {"isin": "INE009A01021", "sector": "IT",             "base": 1834.20},
    "WIPRO":     {"isin": "INE075A01022", "sector": "IT",             "base": 462.80},
    "ICICIBANK": {"isin": "INE090A01021", "sector": "Banking",        "base": 1198.60},
    "SBIN":      {"isin": "INE062A01020", "sector": "Banking",        "base": 812.35},
    "BAJFINANCE":{"isin": "INE296A01024", "sector": "NBFC",           "base": 7234.00},
    "ASIANPAINT":{"isin": "INE021A01026", "sector": "Consumer",       "base": 3187.90},
    "MARUTI":    {"isin": "INE585B01010", "sector": "Auto",           "base": 12850.00},
    "AXISBANK":  {"isin": "INE238A01034", "sector": "Banking",        "base": 1089.75},
    "LT":        {"isin": "INE018A01030", "sector": "Infra",          "base": 3612.40},
    "SUNPHARMA": {"isin": "INE044A01036", "sector": "Pharma",         "base": 1821.55},
    "TATAMOTORS":{"isin": "INE155A01022", "sector": "Auto",           "base": 984.20},
    "ADANIENT":  {"isin": "INE423A01024", "sector": "Conglomerate",   "base": 2674.30},
    "KOTAKBANK": {"isin": "INE237A01028", "sector": "Banking",        "base": 1876.90},
    "HINDUNILVR":{"isin": "INE030A01027", "sector": "Consumer",       "base": 2478.60},
    "ITC":       {"isin": "INE154A01025", "sector": "Consumer",       "base": 467.25},
    "POWERGRID": {"isin": "INE752E01010", "sector": "Utilities",      "base": 329.80},
    "NTPC":      {"isin": "INE733E01010", "sector": "Utilities",      "base": 378.45},
}

_MOCK_ACCOUNTS_SEED: Dict[str, dict] = {
    "zerodha_primary": {
        "display_name": "Zerodha Primary",
        "owner": "Ramesh Kumar",
        "user_id": "RK1234",
        "email": "rameshkumar4388@gmail.com",
        "holdings": [
            {"symbol": "RELIANCE",   "qty": 150, "avg": 2320.00},
            {"symbol": "TCS",        "qty": 80,  "avg": 3450.00},
            {"symbol": "HDFCBANK",   "qty": 200, "avg": 1520.00},
            {"symbol": "INFY",       "qty": 120, "avg": 1640.00},
            {"symbol": "ICICIBANK",  "qty": 300, "avg": 980.00},
            {"symbol": "SBIN",       "qty": 500, "avg": 620.00},
            {"symbol": "AXISBANK",   "qty": 250, "avg": 920.00},
            {"symbol": "KOTAKBANK",  "qty": 100, "avg": 1720.00},
        ],
        "positions": [
            {
                "symbol": "NIFTY2561924500CE",
                "underlying": "NIFTY",
                "exchange": "NFO",
                "product": "NRML",
                "instrument_type": "CE",
                "qty": 75,
                "avg": 142.50,
                "lot_size": 75,
                "expiry": "2025-06-19",
                "strike": 24500.0,
                "ltp": 187.30,
            },
            {
                "symbol": "NIFTY25JUNFUT",
                "underlying": "NIFTY",
                "exchange": "NFO",
                "product": "NRML",
                "instrument_type": "FUT",
                "qty": 75,
                "avg": 24380.00,
                "lot_size": 75,
                "expiry": "2025-06-26",
                "strike": None,
                "ltp": 24520.00,
            },
        ],
        "available_cash": 182450.00,
        "used_margin": 384200.00,
        "span_margin": 210000.00,
        "exposure_margin": 174200.00,
    },
    "zerodha_trading": {
        "display_name": "Zerodha Trading",
        "owner": "Ramesh Kumar",
        "user_id": "RK5678",
        "email": "rameshkumar4388@gmail.com",
        "holdings": [
            {"symbol": "WIPRO",      "qty": 500, "avg": 410.00},
            {"symbol": "BAJFINANCE", "qty": 50,  "avg": 6800.00},
            {"symbol": "MARUTI",     "qty": 30,  "avg": 11200.00},
            {"symbol": "SUNPHARMA",  "qty": 180, "avg": 1620.00},
            {"symbol": "TATAMOTORS", "qty": 400, "avg": 820.00},
        ],
        "positions": [
            {
                "symbol": "BANKNIFTY2561944000PE",
                "underlying": "BANKNIFTY",
                "exchange": "NFO",
                "product": "NRML",
                "instrument_type": "PE",
                "qty": -30,
                "avg": 312.00,
                "lot_size": 30,
                "expiry": "2025-06-19",
                "strike": 44000.0,
                "ltp": 278.50,
            },
            {
                "symbol": "RELIANCE25JUNFUT",
                "underlying": "RELIANCE",
                "exchange": "NFO",
                "product": "NRML",
                "instrument_type": "FUT",
                "qty": 250,
                "avg": 2780.00,
                "lot_size": 250,
                "expiry": "2025-06-26",
                "strike": None,
                "ltp": 2847.50,
            },
            {
                "symbol": "SBIN",
                "underlying": "SBIN",
                "exchange": "NSE",
                "product": "MIS",
                "instrument_type": "EQ",
                "qty": 1000,
                "avg": 808.00,
                "lot_size": 1,
                "expiry": None,
                "strike": None,
                "ltp": 812.35,
            },
        ],
        "available_cash": 548200.00,
        "used_margin": 892400.00,
        "span_margin": 520000.00,
        "exposure_margin": 372400.00,
    },
    "groww_invest": {
        "display_name": "Groww Investment",
        "owner": "Ramesh Kumar",
        "user_id": "GW9012",
        "email": "rameshkumar4388@gmail.com",
        "holdings": [
            {"symbol": "HINDUNILVR", "qty": 120, "avg": 2280.00},
            {"symbol": "ITC",        "qty": 800, "avg": 420.00},
            {"symbol": "ASIANPAINT", "qty": 60,  "avg": 2900.00},
            {"symbol": "LT",         "qty": 90,  "avg": 3280.00},
            {"symbol": "POWERGRID",  "qty": 1000,"avg": 298.00},
            {"symbol": "NTPC",       "qty": 700, "avg": 340.00},
            {"symbol": "ADANIENT",   "qty": 100, "avg": 2420.00},
        ],
        "positions": [],
        "available_cash": 94780.00,
        "used_margin": 0.0,
        "span_margin": 0.0,
        "exposure_margin": 0.0,
    },
    "zerodha_fxu722": {
        "display_name": "Zerodha (FXU722)",
        "owner": "Ramesh Kumar",
        "user_id": "FXU722",
        "email": "rameshkumar4388@gmail.com",
        "holdings": [
            {"symbol": "HDFCBANK",   "qty": 300, "avg": 1480.00},
            {"symbol": "ICICIBANK",  "qty": 400, "avg": 950.00},
            {"symbol": "KOTAKBANK",  "qty": 150, "avg": 1700.00},
            {"symbol": "AXISBANK",   "qty": 200, "avg": 890.00},
        ],
        "positions": [
            {
                "symbol": "NIFTY25JUNFUT",
                "underlying": "NIFTY",
                "exchange": "NFO",
                "product": "NRML",
                "instrument_type": "FUT",
                "qty": -75,
                "avg": 24450.00,
                "lot_size": 75,
                "expiry": "2025-06-26",
                "strike": None,
                "ltp": 24520.00,
            },
        ],
        "available_cash": 312000.00,
        "used_margin": 198000.00,
        "span_margin": 120000.00,
        "exposure_margin": 78000.00,
    },
    "zerodha_da1898": {
        "display_name": "Zerodha (DA1898)",
        "owner": "Ramesh Kumar",
        "user_id": "DA1898",
        "email": "rameshkumar4388@gmail.com",
        "holdings": [
            {"symbol": "TCS",        "qty": 60,  "avg": 3600.00},
            {"symbol": "INFY",       "qty": 100, "avg": 1720.00},
            {"symbol": "WIPRO",      "qty": 350, "avg": 430.00},
            {"symbol": "MARUTI",     "qty": 20,  "avg": 11500.00},
            {"symbol": "SUNPHARMA",  "qty": 120, "avg": 1580.00},
        ],
        "positions": [],
        "available_cash": 87450.00,
        "used_margin": 0.0,
        "span_margin": 0.0,
        "exposure_margin": 0.0,
    },
}


class MockAdapter(BrokerAdapter):
    """
    Fully functional mock adapter. Generates deterministic seed data
    with slight random variation to simulate live market movement.
    In a real deployment this is replaced by the live broker adapter.
    """

    @property
    def broker_name(self) -> str:
        return "mock"

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        return account_id in _MOCK_ACCOUNTS_SEED

    def is_session_valid(self, account_id: str) -> bool:
        return account_id in _MOCK_ACCOUNTS_SEED

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _seed(self, account_id: str) -> dict:
        return _MOCK_ACCOUNTS_SEED.get(account_id, {})

    def _mock_ltp(self, symbol: str, base_override: Optional[float] = None) -> float:
        base = base_override or _EQUITY_UNIVERSE.get(symbol, {}).get("base", 100.0)
        variation = random.uniform(-0.015, 0.015)
        return round(base * (1 + variation), 2)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        seed = self._seed(account_id)
        if not seed:
            return None
        return AccountInfo(
            account_id=account_id,
            broker="mock",
            display_name=seed["display_name"],
            owner=seed["owner"],
            user_id=seed.get("user_id", account_id),
            email=seed.get("email"),
            is_active=True,
            metadata={"original_broker": account_id.split("_")[0]},
        )

    def get_holdings(self, account_id: str) -> List[Holding]:
        seed = self._seed(account_id)
        if not seed:
            return []

        holdings: List[Holding] = []
        for h in seed.get("holdings", []):
            sym = h["symbol"]
            meta = _EQUITY_UNIVERSE.get(sym, {})
            ltp = self._mock_ltp(sym)
            avg = h["avg"]
            qty = h["qty"]

            holding = Holding(
                account_id=account_id,
                broker="mock",
                symbol=sym,
                exchange="NSE",
                isin=meta.get("isin", "INE000000000"),
                quantity=qty,
                avg_price=avg,
                ltp=ltp,
                sector=meta.get("sector", "Unknown"),
                instrument_type="EQ",
            )
            holding.day_change = round(ltp - meta.get("base", ltp) * random.uniform(0.99, 1.00), 2)
            holding.day_change_pct = round((holding.day_change / ltp) * 100, 2) if ltp else 0.0
            holdings.append(holding)

        return holdings

    def get_positions(self, account_id: str) -> List[Position]:
        seed = self._seed(account_id)
        if not seed:
            return []

        positions: List[Position] = []
        for p in seed.get("positions", []):
            ltp = p.get("ltp", self._mock_ltp(p["symbol"]))
            variation = random.uniform(-0.008, 0.008)
            ltp = round(ltp * (1 + variation), 2)

            qty = p["qty"]
            avg = p["avg"]
            lot = p.get("lot_size", 1)
            # qty already represents total contracted shares; lot_size is informational
            cost  = qty * avg
            value = qty * ltp
            pnl   = round(value - cost, 2)

            pos = Position(
                account_id=account_id,
                broker="mock",
                symbol=p["symbol"],
                exchange=p.get("exchange", "NSE"),
                product=p["product"],
                instrument_type=p["instrument_type"],
                quantity=qty,
                avg_price=avg,
                ltp=ltp,
                pnl=pnl,
                day_pnl=round(pnl * random.uniform(0.3, 0.7), 2),
                value=value,
                lot_size=lot,
                expiry=p.get("expiry"),
                strike=p.get("strike"),
                underlying=p.get("underlying", p["symbol"]),
                tradingsymbol=p["symbol"],
            )
            positions.append(pos)

        return positions

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        seed = self._seed(account_id)
        if not seed:
            return None
        cash       = seed.get("available_cash", 0.0)
        used       = seed.get("used_margin", 0.0)
        collateral = seed.get("total_collateral", 0.0)
        return MarginInfo(
            account_id=account_id,
            broker="mock",
            available_cash=cash,
            used_margin=used,
            span_margin=seed.get("span_margin", 0.0),
            exposure_margin=seed.get("exposure_margin", 0.0),
            total_collateral=collateral,
            net_available=max(cash + collateral - used, 0.0),
        )

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        holdings = self.get_holdings(account_id)
        positions = self.get_positions(account_id)
        margin = self.get_margin(account_id)
        info = self.get_account_info(account_id)

        if not info:
            return None

        total_holdings_value = sum(h.current_value for h in holdings)
        total_invested = sum(h.invested_value for h in holdings)
        holdings_pnl = sum(h.pnl for h in holdings)
        positions_pnl = sum(p.pnl for p in positions)
        day_pnl = (
            sum(h.day_change * h.quantity for h in holdings)
            + sum(p.day_pnl for p in positions)
        )

        available_cash = margin.available_cash if margin else 0.0
        used_margin = margin.used_margin if margin else 0.0

        net_worth = total_holdings_value + available_cash

        return AccountSummary(
            account_id=account_id,
            broker="mock",
            display_name=info.display_name,
            owner=info.owner,
            total_holdings_value=round(total_holdings_value, 2),
            total_invested_value=round(total_invested, 2),
            holdings_pnl=round(holdings_pnl, 2),
            holdings_pnl_pct=round((holdings_pnl / total_invested) * 100, 2) if total_invested else 0.0,
            positions_pnl=round(positions_pnl, 2),
            day_pnl=round(day_pnl, 2),
            available_cash=available_cash,
            used_margin=used_margin,
            net_worth=round(net_worth, 2),
        )
