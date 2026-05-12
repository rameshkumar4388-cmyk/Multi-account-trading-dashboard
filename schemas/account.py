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
    # Cash-only balance (no collateral, no intraday credits)
    available_cash: float = 0.0
    # Total available for trading = cash + collateral - utilised
    net_available: float = 0.0
    # Margin currently blocked (SPAN + exposure + option premium + etc.)
    used_margin: float = 0.0
    # Value of pledged holdings approved as collateral (after haircut)
    total_collateral: float = 0.0
    # SPAN margin component of used_margin
    span_margin: float = 0.0
    # Exposure margin component of used_margin
    exposure_margin: float = 0.0
    # Option premium blocked
    option_premium: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AccountSummary:
    account_id: str
    broker: str
    display_name: str
    owner: str
    # Holdings metrics
    total_holdings_value: float = 0.0   # Market value of all holdings (free + T1 + pledged)
    total_invested_value: float = 0.0   # Cost basis of all holdings
    holdings_pnl: float = 0.0          # Unrealized P&L on holdings
    holdings_pnl_pct: float = 0.0
    # Position metrics
    positions_pnl: float = 0.0         # Unrealized P&L on open positions
    realised_pnl: float = 0.0          # Realized P&L from closed positions today
    # Margin and cash
    available_cash: float = 0.0        # Pure cash balance
    net_available: float = 0.0         # Total available margin (cash + collateral - used)
    used_margin: float = 0.0           # Margin currently blocked
    total_collateral: float = 0.0      # Collateral from pledged holdings
    # Day metrics
    day_pnl: float = 0.0               # holdings day change + positions day m2m
    holdings_day_pnl: float = 0.0      # holdings-only day movement (for spec metric 2)
    day_pnl_pct: float = 0.0
    # Totals
    net_worth: float = 0.0             # Holdings value + cash + positions MTM P&L
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def total_pnl(self) -> float:
        return self.holdings_pnl + self.positions_pnl + self.realised_pnl
