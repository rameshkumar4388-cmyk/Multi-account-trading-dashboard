from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).parent.parent


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
    ui_refresh_interval: int = 5    # seconds, for Streamlit autorefresh
    accounts: List[AccountConfig] = field(default_factory=list)


def _load_accounts_from_env() -> List[AccountConfig]:
    """Build account configs from environment variables."""
    accounts: List[AccountConfig] = []

    zerodha_indices = []
    for key in os.environ:
        if key.startswith("ZERODHA_") and key.endswith("_API_KEY"):
            tag = key[len("ZERODHA_"):-len("_API_KEY")]
            zerodha_indices.append(tag)

    for tag in zerodha_indices:
        api_key = os.getenv(f"ZERODHA_{tag}_API_KEY", "")
        api_secret = os.getenv(f"ZERODHA_{tag}_API_SECRET", "")
        access_token = os.getenv(f"ZERODHA_{tag}_ACCESS_TOKEN", "")
        user_id = os.getenv(f"ZERODHA_{tag}_USER_ID", f"zerodha_{tag.lower()}")

        if api_key and api_key != "your_api_key_here":
            accounts.append(AccountConfig(
                account_id=f"zerodha_{tag.lower()}",
                broker="zerodha",
                display_name=f"Zerodha {tag}",
                owner=user_id,
                enabled=True,
                credentials={
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "access_token": access_token,
                    "user_id": user_id,
                },
            ))

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


def load_settings() -> AppSettings:
    mode = os.getenv("APP_MODE", "mock").lower()
    db_path = os.getenv("DB_PATH", "data/dashboard.db")

    if mode == "live":
        accounts = _load_accounts_from_env()
        if not accounts:
            mode = "mock"
            accounts = _mock_accounts()
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
