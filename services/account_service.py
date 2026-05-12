"""
Account service — manages broker adapter lifecycle for all configured accounts.

Key responsibilities:
  - Instantiate the correct adapter per configured account
  - On startup: prefer a fresh stored token (SQLite) over the .env token
  - Authenticate each account independently; one failure never blocks others
  - Track per-account health (active / auth_failed / error) with error details
  - Expose refresh_session() for hot-swap of access tokens without restart
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
    def __init__(self, settings: AppSettings, db=None):
        """
        Args:
            settings: Loaded AppSettings (from config.settings.load_settings)
            db:       Optional Database instance for token persistence.
                      When provided, stored tokens take priority over .env tokens
                      if they are fresh (generated today after 06:00 IST).
        """
        self._settings = settings
        self._db = db
        self._adapters: Dict[str, BrokerAdapter] = {}
        self._health: Dict[str, AccountHealth] = {}
        self._account_configs: Dict[str, AccountConfig] = {
            a.account_id: a for a in settings.accounts if a.enabled
        }
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self):
        if self._initialized:
            return

        for cfg in self._account_configs.values():
            # In live mode: check token store for a fresher access_token
            if self._settings.app_mode == "live" and self._db and cfg.broker == "zerodha":
                self._maybe_load_stored_token(cfg)
            self._init_account(cfg)

        active = sum(1 for h in self._health.values() if h.is_active)
        failed = len(self._health) - active
        logger.info(
            "AccountService ready: %d active, %d failed (total configured: %d)",
            active, failed, len(self._account_configs),
        )
        self._initialized = True

    def _maybe_load_stored_token(self, cfg: AccountConfig):
        """
        If a fresh stored token exists in the database, replace the .env token
        in this config's credentials before authentication is attempted.
        """
        try:
            from brokers.zerodha.token_store import TokenStore
            store = TokenStore(self._db)
            token_row = store.load_fresh(cfg.account_id)
            if token_row:
                stored_token = token_row["access_token"]
                env_token    = cfg.credentials.get("access_token", "")
                if stored_token != env_token:
                    logger.info(
                        "AccountService: using stored token for '%s' "
                        "(generated %s, overrides .env)",
                        cfg.account_id, token_row.get("generated_at", "?"),
                    )
                    cfg.credentials["access_token"] = stored_token
        except Exception as exc:
            logger.warning(
                "AccountService: could not load stored token for '%s': %s",
                cfg.account_id, exc,
            )

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
                # Update display name and user_id from API profile (e.g. "Zerodha (SP7086)").
                # Profile is already cached in the adapter from the auth call — no extra round-trip.
                info = adapter.get_account_info(cfg.account_id)
                if info and info.display_name:
                    health.display_name = info.display_name
                    cfg.display_name    = info.display_name
                if info and info.user_id and not cfg.credentials.get("user_id"):
                    cfg.credentials["user_id"] = info.user_id
                logger.info("Account '%s' (%s) authenticated", cfg.account_id, cfg.display_name)
            else:
                health.error = (
                    getattr(adapter, "last_auth_error", None)
                    or "Authentication returned False"
                )
                logger.warning("Auth failed for '%s': %s", cfg.account_id, health.error)
        except Exception as exc:
            health.status = "error"
            health.error = str(exc)
            logger.error(
                "Exception initialising account '%s': %s",
                cfg.account_id, exc, exc_info=True,
            )
        self._health[cfg.account_id] = health

    # ------------------------------------------------------------------
    # Session refresh (hot-swap — no app restart needed)
    # ------------------------------------------------------------------

    def refresh_session(
        self,
        account_id: str,
        access_token: str,
        api_key: Optional[str] = None,
        user_id: str = "",
        user_name: str = "",
    ) -> bool:
        """
        Replace the access token for an account and re-authenticate in-place.

        Also persists the new token to the database so it survives app restarts.
        Returns True if the new session was established successfully.

        This method is safe to call at any time — it only modifies the named
        account, leaving all other accounts and services untouched.
        """
        cfg = self._account_configs.get(account_id)
        if not cfg:
            logger.warning("refresh_session: unknown account '%s'", account_id)
            return False

        # Update credentials
        cfg.credentials["access_token"] = access_token
        if api_key:
            cfg.credentials["api_key"] = api_key

        # Persist to token store so next restart uses this token automatically
        if self._db:
            try:
                from brokers.zerodha.token_store import TokenStore
                TokenStore(self._db).save(
                    account_id=account_id,
                    api_key=cfg.credentials.get("api_key", ""),
                    access_token=access_token,
                    user_id=user_id,
                    user_name=user_name,
                )
            except Exception as exc:
                logger.error(
                    "refresh_session: failed to persist token for '%s': %s",
                    account_id, exc,
                )

        # Drop the old adapter and re-init with the new token
        self._adapters.pop(account_id, None)
        self._init_account(cfg)

        success = self._health[account_id].is_active
        logger.info(
            "refresh_session '%s': %s",
            account_id, "SUCCESS" if success else "FAILED",
        )
        return success

    def retry_auth(self, account_id: str) -> bool:
        """Re-attempt authentication using the current credentials (no token change)."""
        cfg = self._account_configs.get(account_id)
        if not cfg:
            logger.warning("retry_auth: unknown account '%s'", account_id)
            return False
        self._adapters.pop(account_id, None)
        self._init_account(cfg)
        return self._health[account_id].is_active

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, AccountHealth]:
        return dict(self._health)

    def get_failed_account_ids(self) -> List[str]:
        return [aid for aid, h in self._health.items() if not h.is_active]

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

    def get_kite_sessions(self) -> dict:
        """Return active KiteConnect sessions keyed by account_id (Zerodha only)."""
        sessions: dict = {}
        for aid, adapter in self._adapters.items():
            session = adapter.get_kite_session(aid)
            if session is not None:
                sessions[aid] = session
        return sessions

    def get_all_symbols(self) -> List[str]:
        symbols: List[str] = []
        for aid, adapter in self._adapters.items():
            try:
                symbols.extend(adapter.get_subscribed_symbols(aid))
            except Exception as exc:
                logger.error("Failed to get symbols for %s: %s", aid, exc)
        return list(dict.fromkeys(symbols))

    # ------------------------------------------------------------------
    # Token store helpers (for UI auth page)
    # ------------------------------------------------------------------

    def get_api_credentials(self, account_id: str) -> dict:
        """
        Return non-secret credentials for an account (api_key, display_name).
        Never returns api_secret or access_token.
        """
        cfg = self._account_configs.get(account_id, {})
        if not cfg:
            return {}
        return {
            "account_id": account_id,
            "api_key": cfg.credentials.get("api_key", ""),
            "display_name": cfg.display_name,
            "broker": cfg.broker,
        }
