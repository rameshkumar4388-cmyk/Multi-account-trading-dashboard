"""
Account service — manages broker adapter lifecycle for all configured accounts.

The dashboard never directly instantiates broker adapters. All adapter
access is mediated through this service, which:
  - Instantiates the correct adapter for each configured account
  - Handles authentication and session validation
  - Provides a unified interface for account metadata
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from config.settings import AccountConfig, AppSettings
from schemas.account import AccountInfo

logger = logging.getLogger(__name__)


def _make_adapter(broker: str, mode: str) -> BrokerAdapter:
    """Factory: return the correct adapter for a given broker."""
    if mode == "mock" or broker == "mock":
        from brokers.mock.adapter import MockAdapter
        return MockAdapter()
    if broker == "zerodha":
        from brokers.zerodha.adapter import ZerodhaAdapter
        return ZerodhaAdapter()
    if broker == "groww":
        from brokers.groww.adapter import GrowwAdapter
        return GrowwAdapter()
    if broker == "fivepaisa":
        from brokers.fivepaisa.adapter import FivePaisaAdapter
        return FivePaisaAdapter()
    # Unknown broker falls back to mock
    logger.warning("Unknown broker '%s', falling back to mock adapter", broker)
    from brokers.mock.adapter import MockAdapter
    return MockAdapter()


class AccountService:
    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._adapters: Dict[str, BrokerAdapter] = {}
        self._account_configs: Dict[str, AccountConfig] = {
            a.account_id: a for a in settings.accounts if a.enabled
        }
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        for cfg in self._account_configs.values():
            adapter = _make_adapter(cfg.broker, self._settings.app_mode)
            authenticated = adapter.authenticate(cfg.account_id, cfg.credentials)
            if authenticated:
                self._adapters[cfg.account_id] = adapter
                logger.info("Account '%s' (%s) ready", cfg.account_id, cfg.broker)
            else:
                logger.warning("Authentication failed for account '%s'", cfg.account_id)
        self._initialized = True

    # ------------------------------------------------------------------
    # Account metadata
    # ------------------------------------------------------------------

    def list_account_ids(self) -> List[str]:
        return list(self._adapters.keys())

    def get_account_configs(self) -> List[AccountConfig]:
        return [
            self._account_configs[aid]
            for aid in self._adapters
        ]

    def get_adapter(self, account_id: str) -> Optional[BrokerAdapter]:
        return self._adapters.get(account_id)

    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        adapter = self.get_adapter(account_id)
        return adapter.get_account_info(account_id) if adapter else None

    def get_all_account_infos(self) -> List[AccountInfo]:
        infos = []
        for aid in self._adapters:
            info = self.get_account_info(aid)
            if info:
                infos.append(info)
        return infos

    def get_all_symbols(self) -> List[str]:
        """Collect all unique symbols across all accounts for market data subscription."""
        symbols: List[str] = []
        for aid, adapter in self._adapters.items():
            try:
                symbols.extend(adapter.get_subscribed_symbols(aid))
            except Exception as exc:
                logger.error("Failed to get symbols for %s: %s", aid, exc)
        return list(dict.fromkeys(symbols))
