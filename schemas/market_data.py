from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Quote:
    symbol: str
    exchange: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if self.close > 0:
            self.change = round(self.ltp - self.close, 2)
            self.change_pct = round((self.change / self.close) * 100, 2)


@dataclass
class Tick:
    """Lightweight tick from websocket feed."""
    symbol: str
    ltp: float
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
