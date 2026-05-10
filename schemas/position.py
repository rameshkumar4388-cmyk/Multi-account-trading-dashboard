from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    account_id: str
    broker: str
    symbol: str
    exchange: str
    product: str            # "MIS" | "NRML" | "CNC"
    instrument_type: str    # "EQ" | "FUT" | "CE" | "PE"
    quantity: int           # net quantity (+long, -short)
    avg_price: float
    ltp: float = 0.0
    pnl: float = 0.0
    day_pnl: float = 0.0
    value: float = 0.0
    buy_quantity: int = 0
    sell_quantity: int = 0
    expiry: Optional[str] = None
    strike: Optional[float] = None
    lot_size: int = 1
    tradingsymbol: str = ""
    underlying: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.tradingsymbol:
            self.tradingsymbol = self.symbol
        if not self.underlying:
            self.underlying = self.symbol
        self._recompute(self.ltp)

    def _recompute(self, ltp: float):
        if ltp > 0:
            self.ltp = ltp
            self.value = round(self.quantity * ltp * self.lot_size, 2)
            cost = self.quantity * self.avg_price * self.lot_size
            self.pnl = round(self.value - cost, 2)

    def update_ltp(self, ltp: float):
        self._recompute(ltp)
        self.timestamp = datetime.now()

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def direction(self) -> str:
        return "LONG" if self.is_long else "SHORT"
