"""
Server-side Zerodha access token persistence.

Tokens are stored in the SQLite database (never in .env or browser).
A token is considered valid if it was generated today before 6 AM IST
(Zerodha expires tokens at 6 AM IST each day).

api_secret is intentionally NOT stored — it stays in .env only.
The access_token is the only secret written to the database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Zerodha tokens expire at 06:00 IST (UTC+5:30) each day
_IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(_IST)


def _token_expiry_for_today() -> datetime:
    """Return 06:00 IST on the NEXT calendar day (when today's token expires)."""
    now = _ist_now()
    # If we're before 06:00 today, the token from yesterday is still valid
    # (it expires at today's 06:00). We generate_at timestamps and compare.
    next_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < next_6am:
        return next_6am
    # After 06:00 today, return tomorrow's 06:00
    return next_6am + timedelta(days=1)


class TokenStore:
    """
    Read/write Zerodha access tokens to/from the dashboard SQLite database.
    Thread-safe via the Database class's WAL-mode connection.
    """

    def __init__(self, db):
        """
        Args:
            db: Database instance from database.db.Database
        """
        self._db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(
        self,
        account_id: str,
        api_key: str,
        access_token: str,
        user_id: str = "",
        user_name: str = "",
    ):
        """Persist a new access_token for an account."""
        generated_at = _ist_now().isoformat()
        self._db.execute(
            """
            INSERT INTO stored_tokens
                (account_id, api_key, access_token, generated_at, user_id, user_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                api_key=excluded.api_key,
                access_token=excluded.access_token,
                generated_at=excluded.generated_at,
                user_id=excluded.user_id,
                user_name=excluded.user_name
            """,
            (account_id, api_key, access_token, generated_at, user_id, user_name),
        )
        self._db.commit()
        logger.info(
            "TokenStore: saved token for '%s' (user=%s generated=%s)",
            account_id, user_name or user_id, generated_at,
        )

    def delete(self, account_id: str):
        self._db.execute(
            "DELETE FROM stored_tokens WHERE account_id = ?", (account_id,)
        )
        self._db.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self, account_id: str) -> Optional[dict]:
        """
        Return the stored token dict or None if not found.
        Does NOT check freshness — call is_fresh() separately.
        """
        row = self._db.fetchone(
            "SELECT * FROM stored_tokens WHERE account_id = ?", (account_id,)
        )
        if not row:
            return None
        return dict(row)

    def is_fresh(self, account_id: str) -> bool:
        """
        Return True if the stored token is still valid (not yet expired).
        Zerodha tokens expire at 06:00 IST the day after generation.
        """
        row = self._db.fetchone(
            "SELECT generated_at FROM stored_tokens WHERE account_id = ?",
            (account_id,),
        )
        if not row:
            return False
        try:
            generated_at = datetime.fromisoformat(row["generated_at"])
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=_IST)
            # Token is fresh if it was generated after the most recent 06:00 IST
            now = _ist_now()
            today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now < today_6am:
                # Before today's 06:00 — token valid if generated after yesterday's 06:00
                cutoff = today_6am - timedelta(days=1)
            else:
                # After today's 06:00 — token valid if generated after today's 06:00
                cutoff = today_6am
            return generated_at >= cutoff
        except Exception as exc:
            logger.warning("TokenStore.is_fresh(): could not parse timestamp: %s", exc)
            return False

    def load_fresh(self, account_id: str) -> Optional[dict]:
        """Return token dict only if it's still fresh; None otherwise."""
        if not self.is_fresh(account_id):
            return None
        return self.load(account_id)

    def list_all(self) -> list:
        """Return all stored token rows (without access_token values for safety)."""
        rows = self._db.fetchall(
            "SELECT account_id, api_key, generated_at, user_id, user_name FROM stored_tokens"
        )
        return [dict(r) for r in rows]
