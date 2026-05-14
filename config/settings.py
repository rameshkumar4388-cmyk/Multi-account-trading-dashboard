from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).parent.parent
logger = logging.getLogger(__name__)

# Values that mean "not configured yet" — treated as missing
_PLACEHOLDER_VALUES = {
    "", "your_api_key_here", "your_api_secret_here",
    "your_access_token_here", "your_user_id_here",
    "xxx", "PLACEHOLDER", "changeme",
}


@dataclass
class AccountConfig:
    account_id: str
    broker: str
    display_name: str
    owner: str
    enabled: bool = True
    credentials: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class AppSettings:
    app_mode: str = "mock"          # "mock" | "live"
    db_path: str = "data/dashboard.db"
    account_refresh_interval: int = 30
    market_data_refresh_interval: int = 5
    ui_refresh_interval: int = 5
    accounts: List[AccountConfig] = field(default_factory=list)
    # Account whose KiteConnect session is used exclusively for all market-data
    # calls (LTP, quotes, index prices, WebSocket ticks).  Must be a paid Kite
    # Connect account with live data entitlement.  Other accounts are NEVER used
    # for market data even if they have valid sessions.
    market_data_account_id: Optional[str] = None


def _is_placeholder(value: str) -> bool:
    return not value or value.strip() in _PLACEHOLDER_VALUES


def _load_accounts_from_env() -> List[AccountConfig]:
    """
    Dynamically discover all Zerodha accounts from environment variables.

    Discovery rule: any env var matching ZERODHA_<TAG>_API_KEY registers
    a new account with tag TAG.  TAG can be any identifier — ACC1, PROD,
    FAMILY, TRADING, etc.  Accounts are registered in sorted tag order so
    the list is deterministic regardless of OS env ordering.

    Required per account:
        ZERODHA_<TAG>_API_KEY
        ZERODHA_<TAG>_ACCESS_TOKEN

    Optional per account:
        ZERODHA_<TAG>_API_SECRET     (needed for token refresh only)
        ZERODHA_<TAG>_USER_ID
        ZERODHA_<TAG>_DISPLAY_NAME   (shown in the UI; defaults to "Zerodha <TAG>")
    """
    # ── 1. Discover all unique tags ───────────────────────────────────
    tags: set[str] = set()
    for key in os.environ:
        if key.startswith("ZERODHA_") and key.endswith("_API_KEY"):
            tag = key[len("ZERODHA_"):-len("_API_KEY")]
            if tag:
                tags.add(tag)

    if not tags:
        logger.info("No ZERODHA_*_API_KEY entries found in environment.")
        return []

    # ── 2. Build configs, skip any with missing required fields ───────
    accounts: List[AccountConfig] = []
    for tag in sorted(tags):
        prefix = f"ZERODHA_{tag}"

        api_key      = os.getenv(f"{prefix}_API_KEY", "").strip()
        api_secret   = os.getenv(f"{prefix}_API_SECRET", "").strip()
        access_token = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
        user_id      = os.getenv(f"{prefix}_USER_ID", "").strip()
        display_name = os.getenv(f"{prefix}_DISPLAY_NAME", f"Zerodha ({tag})").strip()

        # Validate required fields
        missing: List[str] = []
        if _is_placeholder(api_key):
            missing.append(f"ZERODHA_{tag}_API_KEY")
        if _is_placeholder(access_token):
            missing.append(f"ZERODHA_{tag}_ACCESS_TOKEN")

        if missing:
            logger.warning(
                "Skipping account ZERODHA_%s — missing or placeholder value(s): %s",
                tag, ", ".join(missing),
            )
            continue

        account_id = f"zerodha_{tag.lower()}"
        accounts.append(AccountConfig(
            account_id=account_id,
            broker="zerodha",
            display_name=display_name,
            owner=user_id or display_name,
            enabled=True,
            credentials={
                "api_key": api_key,
                "api_secret": api_secret,
                "access_token": access_token,
                "user_id": user_id,
            },
            metadata={
                "tag": tag,
                "original_broker": "zerodha",
                "account_type": "live",
            },
        ))
        logger.info("Registered Zerodha account: %s (%s)", account_id, display_name)

    return accounts


def _mock_accounts() -> List[AccountConfig]:
    return [
        AccountConfig(
            account_id="zerodha_primary",
            broker="mock",
            display_name="Zerodha Primary",
            owner="Ramesh Kumar",
            enabled=True,
            metadata={"original_broker": "zerodha", "account_type": "individual"},
        ),
        AccountConfig(
            account_id="zerodha_trading",
            broker="mock",
            display_name="Zerodha Trading",
            owner="Ramesh Kumar",
            enabled=True,
            metadata={"original_broker": "zerodha", "account_type": "trading"},
        ),
        AccountConfig(
            account_id="groww_invest",
            broker="mock",
            display_name="Groww Investment",
            owner="Ramesh Kumar",
            enabled=True,
            metadata={"original_broker": "groww", "account_type": "investment"},
        ),
        AccountConfig(
            account_id="zerodha_fxu722",
            broker="mock",
            display_name="Zerodha (FXU722)",
            owner="Ramesh Kumar",
            enabled=True,
            metadata={"original_broker": "zerodha", "account_type": "individual"},
        ),
        AccountConfig(
            account_id="zerodha_da1898",
            broker="mock",
            display_name="Zerodha (DA1898)",
            owner="Ramesh Kumar",
            enabled=True,
            metadata={"original_broker": "zerodha", "account_type": "individual"},
        ),
    ]


def _load_kite_single_account_from_env() -> List[AccountConfig]:
    """
    Support the simple flat naming convention:
        KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN
        KITE_USER_ID, KITE_DISPLAY_NAME  (optional)

    This is an alternative to ZERODHA_<TAG>_* for setups with one account.
    Also accepts ZERODHA_API_KEY / ZERODHA_ACCESS_TOKEN (no tag) as aliases.
    """
    for prefix, default_acct_id, default_name in [
        ("KITE",    "zerodha_sp7086", "Zerodha"),
        ("ZERODHA", "zerodha_primary", "Zerodha"),
    ]:
        api_key      = os.getenv(f"{prefix}_API_KEY", "").strip()
        api_secret   = os.getenv(f"{prefix}_API_SECRET", "").strip()
        access_token = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
        user_id      = os.getenv(f"{prefix}_USER_ID", "").strip()
        display_name = os.getenv(f"{prefix}_DISPLAY_NAME", default_name).strip()

        if _is_placeholder(api_key) or _is_placeholder(access_token):
            continue

        # Derive canonical account_id from user_id (SP7086 → zerodha_sp7086) so
        # flat KITE_* credentials produce the same id as ZERODHA_SP7086_* would.
        acct_id = f"zerodha_{user_id.lower()}" if user_id else default_acct_id

        logger.info("Registered account via %s_* env vars: %s", prefix, acct_id)
        return [AccountConfig(
            account_id=acct_id,
            broker="zerodha",
            display_name=display_name,
            owner=user_id or display_name,
            enabled=True,
            credentials={
                "api_key": api_key,
                "api_secret": api_secret,
                "access_token": access_token,
                "user_id": user_id,
            },
            metadata={"original_broker": "zerodha", "account_type": "live"},
        )]

    return []


def _load_fivepaisa_accounts_from_env() -> List[AccountConfig]:
    """
    Dynamically discover all 5paisa accounts from environment variables.

    Discovery rule: any env var matching FIVEPAISA_<TAG>_CLIENT_CODE registers
    a new account.  TAG can be any identifier (e.g. MAIN, SPOUSE, DA1898).

    Required per account:
        FIVEPAISA_<TAG>_APP_NAME         — API app name
        FIVEPAISA_<TAG>_APP_SOURCE       — API app source (numeric, e.g. 27773)
        FIVEPAISA_<TAG>_USER_ID          — API user ID
        FIVEPAISA_<TAG>_USER_KEY         — API user key
        FIVEPAISA_<TAG>_ENCRYPTION_KEY   — API encryption key
        FIVEPAISA_<TAG>_ACCESS_TOKEN     — daily access token
        FIVEPAISA_<TAG>_CLIENT_CODE      — 5paisa client code (e.g. "12345678")

    Optional per account:
        FIVEPAISA_<TAG>_PASSWORD         — defaults to "dummy" (not needed for token auth)
        FIVEPAISA_<TAG>_DISPLAY_NAME     — shown in UI; defaults to "5paisa (<TAG>)"
    """
    tags: set[str] = set()
    for key in os.environ:
        if key.startswith("FIVEPAISA_") and key.endswith("_CLIENT_CODE"):
            tag = key[len("FIVEPAISA_"):-len("_CLIENT_CODE")]
            if tag:
                tags.add(tag)

    if not tags:
        return []

    accounts: List[AccountConfig] = []
    for tag in sorted(tags):
        prefix = f"FIVEPAISA_{tag}"

        app_name       = os.getenv(f"{prefix}_APP_NAME", "").strip()
        app_source     = os.getenv(f"{prefix}_APP_SOURCE", "").strip()
        user_id        = os.getenv(f"{prefix}_USER_ID", "").strip()
        user_key       = os.getenv(f"{prefix}_USER_KEY", "").strip()
        encryption_key = os.getenv(f"{prefix}_ENCRYPTION_KEY", "").strip()
        password       = os.getenv(f"{prefix}_PASSWORD", "dummy").strip() or "dummy"
        access_token   = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
        client_code    = os.getenv(f"{prefix}_CLIENT_CODE", "").strip()
        display_name   = os.getenv(f"{prefix}_DISPLAY_NAME", f"5paisa ({tag})").strip()

        missing: List[str] = []
        for field_name, value in [
            (f"FIVEPAISA_{tag}_APP_NAME",       app_name),
            (f"FIVEPAISA_{tag}_APP_SOURCE",      app_source),
            (f"FIVEPAISA_{tag}_USER_ID",         user_id),
            (f"FIVEPAISA_{tag}_USER_KEY",        user_key),
            (f"FIVEPAISA_{tag}_ENCRYPTION_KEY",  encryption_key),
            (f"FIVEPAISA_{tag}_ACCESS_TOKEN",    access_token),
            (f"FIVEPAISA_{tag}_CLIENT_CODE",     client_code),
        ]:
            if _is_placeholder(value):
                missing.append(field_name)

        if missing:
            logger.warning(
                "Skipping 5paisa account FIVEPAISA_%s — missing: %s",
                tag, ", ".join(missing),
            )
            continue

        account_id = f"fivepaisa_{tag.lower()}"
        accounts.append(AccountConfig(
            account_id=account_id,
            broker="fivepaisa",
            display_name=display_name,
            owner=client_code,
            enabled=True,
            credentials={
                "app_name":       app_name,
                "app_source":     app_source,
                "user_id":        user_id,
                "user_key":       user_key,
                "encryption_key": encryption_key,
                "password":       password,
                "access_token":   access_token,
                "client_code":    client_code,
                "display_name":   display_name,
            },
            metadata={
                "tag":            tag,
                "original_broker":"fivepaisa",
                "account_type":   "live",
            },
        ))
        logger.info("Registered 5paisa account: %s (%s)", account_id, display_name)

    return accounts


def load_settings() -> AppSettings:
    mode    = os.getenv("APP_MODE", "mock").lower().strip()
    db_path = os.getenv("DB_PATH", "data/dashboard.db").strip()

    if mode == "live":
        # Merge all broker discovery sources.  Deduplication by account_id
        # prevents the same account appearing twice across patterns.
        tagged_accounts    = _load_accounts_from_env()
        flat_accounts      = _load_kite_single_account_from_env()
        fivepaisa_accounts = _load_fivepaisa_accounts_from_env()

        seen_ids: set[str] = set()
        accounts: List[AccountConfig] = []
        for a in tagged_accounts + flat_accounts + fivepaisa_accounts:
            if a.account_id not in seen_ids:
                seen_ids.add(a.account_id)
                accounts.append(a)

        if not accounts:
            logger.warning(
                "APP_MODE=live but no valid broker accounts found in .env "
                "(checked ZERODHA_*, KITE_*, FIVEPAISA_*) — "
                "falling back to mock/demo mode."
            )
            mode = "mock"
            accounts = _mock_accounts()
        else:
            logger.info("Live mode: loaded %d account(s) from environment.", len(accounts))
    else:
        accounts = _mock_accounts()

    # Market-data authority: SP7086 is the paid Kite Connect account used
    # exclusively for all LTP/quote/index calls.  Read from env; default to
    # zerodha_sp7086.  Warn explicitly if the resolved ID is not in the
    # loaded account list so the error surfaces at startup, not at runtime.
    _DEFAULT_MD_ACCOUNT = "zerodha_sp7086"
    md_account_id = os.getenv("MARKET_DATA_ACCOUNT_ID", "").strip() or _DEFAULT_MD_ACCOUNT
    if mode == "live":
        account_ids = {a.account_id for a in accounts}
        if md_account_id not in account_ids:
            logger.warning(
                "MARKET_DATA_ACCOUNT_ID '%s' not found in configured accounts %s. "
                "Quote fetching will fail until this account authenticates.",
                md_account_id, sorted(account_ids),
            )

    return AppSettings(
        app_mode=mode,
        db_path=db_path,
        account_refresh_interval=int(os.getenv("ACCOUNT_REFRESH_INTERVAL", 30)),
        market_data_refresh_interval=int(os.getenv("MARKET_DATA_REFRESH_INTERVAL", 5)),
        ui_refresh_interval=5,
        accounts=accounts,
        market_data_account_id=md_account_id,
    )
