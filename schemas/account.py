from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AccountInfo:
    account_id: str
    broker: str
    display_name: str
    owner: str
    is_active: bool = True
    user_id: Optional[str] = None
    email: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class MarginInfo:
    account_id: str
    broker: str
    available_cash: float = 0.0
    used_margin: float = 0.0
    total_collateral: float = 0.0
    net_available: float = 0.0
    span_margin: float = 0.0
    exposure_margin: float = 0.0
    option_premium: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AccountSummary:
    account_id: str
    broker: str
    display_name: str
    owner: str
    total_holdings_value: float = 0.0
    total_invested_value: float = 0.0
    holdings_pnl: float = 0.0
    holdings_pnl_pct: float = 0.0
    positions_pnl: float = 0.0
    day_pnl: float = 0.0
    day_pnl_pct: float = 0.0
    available_cash: float = 0.0
    used_margin: float = 0.0
    net_worth: float = 0.0
    total_collateral: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def total_pnl(self) -> float:
        return self.holdings_pnl + self.positions_pnl
