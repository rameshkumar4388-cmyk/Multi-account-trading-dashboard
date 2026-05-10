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
        display_name = os.getenv(f"{prefix}_DISPLAY_NAME", f"Zerodha {tag}").strip()

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
    ]


def _load_kite_single_account_from_env() -> List[AccountConfig]:
    """
    Support the simple flat naming convention:
        KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN
        KITE_USER_ID, KITE_DISPLAY_NAME  (optional)

    This is an alternative to ZERODHA_<TAG>_* for setups with one account.
    Also accepts ZERODHA_API_KEY / ZERODHA_ACCESS_TOKEN (no tag) as aliases.
    """
    for prefix, acct_id, default_name in [
        ("KITE",    "zerodha_kite",    "Zerodha (Kite)"),
        ("ZERODHA", "zerodha_primary", "Zerodha"),
    ]:
        api_key      = os.getenv(f"{prefix}_API_KEY", "").strip()
        api_secret   = os.getenv(f"{prefix}_API_SECRET", "").strip()
        access_token = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
        user_id      = os.getenv(f"{prefix}_USER_ID", "").strip()
        display_name = os.getenv(f"{prefix}_DISPLAY_NAME", default_name).strip()

        if _is_placeholder(api_key) or _is_placeholder(access_token):
            continue

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


def load_settings() -> AppSettings:
    mode    = os.getenv("APP_MODE", "mock").lower().strip()
    db_path = os.getenv("DB_PATH", "data/dashboard.db").strip()

    if mode == "live":
        # Try tagged multi-account pattern first, then flat single-account pattern
        accounts = _load_accounts_from_env() or _load_kite_single_account_from_env()
        if not accounts:
            logger.warning(
                "APP_MODE=live but no valid Zerodha accounts found in .env — "
                "falling back to mock/demo mode."
            )
            mode = "mock"
            accounts = _mock_accounts()
        else:
            logger.info("Live mode: loaded %d account(s) from environment.", len(accounts))
    else:
        accounts = _mock_accounts()

    return AppSettings(
        app_mode=mode,
        db_path=db_path,
        account_refresh_interval=int(os.getenv("ACCOUNT_REFRESH_INTERVAL", 30)),
        market_data_refresh_interval=int(os.getenv("MARKET_DATA_REFRESH_INTERVAL", 5)),
        ui_refresh_interval=5,
        accounts=accounts,
    )
