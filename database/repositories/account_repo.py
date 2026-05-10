from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from database.db import Database
from schemas.account import AccountInfo, AccountSummary, MarginInfo


class AccountRepository:
    def __init__(self, db: Database):
        self._db = db

    def upsert_account(self, info: AccountInfo):
        self._db.execute(
            """
            INSERT INTO accounts (account_id, broker, display_name, owner,
                                  user_id, email, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                display_name=excluded.display_name,
                owner=excluded.owner,
                user_id=excluded.user_id,
                email=excluded.email,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """,
            (
                info.account_id, info.broker, info.display_name, info.owner,
                info.user_id, info.email, int(info.is_active),
                datetime.now().isoformat(),
            ),
        )
        self._db.commit()

    def upsert_margin(self, margin: MarginInfo):
        self._db.execute(
            """
            INSERT INTO margin_cache (account_id, broker, available_cash, used_margin,
                span_margin, exposure_margin, total_collateral, net_available, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                available_cash=excluded.available_cash,
                used_margin=excluded.used_margin,
                span_margin=excluded.span_margin,
                exposure_margin=excluded.exposure_margin,
                total_collateral=excluded.total_collateral,
                net_available=excluded.net_available,
                updated_at=excluded.updated_at
            """,
            (
                margin.account_id, margin.broker, margin.available_cash,
                margin.used_margin, margin.span_margin, margin.exposure_margin,
                margin.total_collateral, margin.net_available,
                datetime.now().isoformat(),
            ),
        )
        self._db.commit()

    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        row = self._db.fetchone(
            "SELECT * FROM margin_cache WHERE account_id = ?", (account_id,)
        )
        if not row:
            return None
        return MarginInfo(
            account_id=row["account_id"],
            broker=row["broker"],
            available_cash=row["available_cash"],
            used_margin=row["used_margin"],
            span_margin=row["span_margin"],
            exposure_margin=row["exposure_margin"],
            total_collateral=row["total_collateral"],
            net_available=row["net_available"],
        )

    def log_refresh(self, account_id: str, data_type: str):
        self._db.execute(
            """
            INSERT INTO refresh_log (account_id, data_type, refreshed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, data_type) DO UPDATE SET refreshed_at=excluded.refreshed_at
            """,
            (account_id, data_type, datetime.now().isoformat()),
        )
        self._db.commit()
