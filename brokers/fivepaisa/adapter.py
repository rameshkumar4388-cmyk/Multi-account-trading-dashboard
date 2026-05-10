"""
5paisa broker adapter — stub implementation.

This module provides the interface contract for future 5paisa integration.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from brokers.base import BrokerAdapter
from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)


class FivePaisaAdapter(BrokerAdapter):
    """
    Placeholder 5paisa adapter.
    Replace method bodies with real 5paisa API calls when available.
    """

    @property
    def broker_name(self) -> str:
        return "fivepaisa"

    def authenticate(self, account_id: str, credentials: dict) -> bool:
        logger.warning("5paisa adapter not yet implemented. Use mock mode.")
        return False

    def is_session_valid(self, account_id: str) -> bool:
        return False

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        return None

    def get_holdings(self, account_id: str) -> List[Holding]:
        return []

    def get_positions(self, account_id: str) -> List[Position]:
        return []

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        return None

    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        return None
