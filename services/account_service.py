"""
Account service — manages broker adapter lifecycle for all configured accounts.

Key responsibilities:
  - Instantiate the correct adapter per configured account
  - Authenticate each account independently; one failure never blocks others
  - Track per-account health (active / auth_failed / error) with error details
  - Expose health status so the UI can show meaningful indicators
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from brokers.base import BrokerAdapter
from config.settings import AccountConfig, AppSettings
from schemas.account import AccountInfo

logger = logging.getLogger(__name__)


# ── Account health ────────────────────────────────────────────────────

@dataclass
class AccountHealth:
    account_id: str
    display_name: str
    broker: str
    status: str                          # "active" | "auth_failed" | "error"
    error: Optional[str] = None
    authenticated_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


# ── Adapter factory ───────────────────────────────────────────────────

def _make_adapter(broker: str, mode: str) -> BrokerAdapter:
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
    logger.warning("Unknown broker '%s', falling back to mock adapter", broker)
    from brokers.mock.adapter import MockAdapter
    return MockAdapter()


# ── Service ───────────────────────────────────────────────────────────

class AccountService:
    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._adapters: Dict[str, BrokerAdapter] = {}
        self._health: Dict[str, AccountHealth] = {}
        self._account_configs: Dict[str, AccountConfig] = {
            a.account_id: a for a in settings.accounts if a.enabled
        }
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return

        for cfg in self._account_configs.values():
            self._init_account(cfg)

        active   = sum(1 for h in self._health.values() if h.is_active)
        failed   = len(self._health) - active
        logger.info(
            "AccountService ready: %d active, %d failed (total configured: %d)",
            active, failed, len(self._account_configs),
        )
        self._initialized = True

    def _init_account(self, cfg: AccountConfig):
        """Authenticate one account; record health regardless of outcome."""
        health = AccountHealth(
            account_id=cfg.account_id,
            display_name=cfg.display_name,
            broker=cfg.broker,
            status="auth_failed",
        )
        try:
            adapter = _make_adapter(cfg.broker, self._settings.app_mode)
            ok = adapter.authenticate(cfg.account_id, cfg.credentials)

            if ok:
                self._adapters[cfg.account_id] = adapter
                health.status = "active"
                health.authenticated_at = datetime.now()
                logger.info("Account '%s' (%s) authenticated", cfg.account_id, cfg.display_name)
            else:
                # Ask the adapter for a human-readable reason if it exposes one
                health.error = getattr(adapter, "last_auth_error", None) or "Authentication returned False"
                logger.warning(
                    "Auth failed for '%s': %s", cfg.account_id, health.error
                )

        except Exception as exc:
            health.status = "error"
            health.error = str(exc)
            logger.error(
                "Exception initialising account '%s': %s",
                cfg.account_id, exc, exc_info=True,
            )

        self._health[cfg.account_id] = health

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, AccountHealth]:
        return dict(self._health)

    def get_failed_account_ids(self) -> List[str]:
        return [aid for aid, h in self._health.items() if not h.is_active]

    def retry_auth(self, account_id: str) -> bool:
        """
        Re-attempt authentication for a single account (e.g. after the user
        has refreshed their Zerodha access token in .env and reloaded).
        Returns True if the retry succeeded.
        """
        cfg = self._account_configs.get(account_id)
        if not cfg:
            logger.warning("retry_auth: unknown account '%s'", account_id)
            return False

        # Remove stale adapter if any
        self._adapters.pop(account_id, None)
        self._init_account(cfg)
        return self._health[account_id].is_active

    # ------------------------------------------------------------------
    # Account metadata
    # ------------------------------------------------------------------

    def list_account_ids(self) -> List[str]:
        return list(self._adapters.keys())

    def get_account_configs(self) -> List[AccountConfig]:
        return [self._account_configs[aid] for aid in self._adapters]

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
        symbols: List[str] = []
        for aid, adapter in self._adapters.items():
            try:
                symbols.extend(adapter.get_subscribed_symbols(aid))
            except Exception as exc:
                logger.error("Failed to get symbols for %s: %s", aid, exc)
        return list(dict.fromkeys(symbols))
