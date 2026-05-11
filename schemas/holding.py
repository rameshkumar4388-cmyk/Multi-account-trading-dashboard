from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Holding:
    account_id: str
    broker: str
    symbol: str
    exchange: str           # "NSE" | "BSE"
    isin: str
    quantity: int
    avg_price: float
    ltp: float = 0.0
    current_value: float = 0.0
    invested_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    day_change: float = 0.0
    day_change_pct: float = 0.0
    sector: str = "Unknown"
    instrument_type: str = "EQ"
    tradingsymbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.tradingsymbol:
            self.tradingsymbol = self.symbol
        self.invested_value = round(self.quantity * self.avg_price, 2)

        if self.ltp > 0:
            # Live price available — compute at market value
            self._recompute(self.ltp)
        else:
            # No LTP yet (pre-market, halted, feed not started).
            # Show at cost basis so net_worth is non-zero until prices arrive.
            self.current_value = self.invested_value
            # pnl / pnl_pct stay 0 — correct, we genuinely don't know the gain

    def _recompute(self, ltp: float):
        if ltp > 0:
            self.ltp = ltp
            self.current_value = round(self.quantity * ltp, 2)
            self.pnl = round(self.current_value - self.invested_value, 2)
            self.pnl_pct = (
                round((self.pnl / self.invested_value) * 100, 2)
                if self.invested_value else 0.0
            )

    def update_ltp(self, ltp: float):
        self._recompute(ltp)
        self.timestamp = datetime.now()
