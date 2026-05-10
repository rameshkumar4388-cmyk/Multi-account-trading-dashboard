"""
SQLite connection manager with thread-safe access.

Uses WAL journal mode for concurrent reads while writes are happening.
The Database singleton is safe to share across Streamlit reruns because
each Streamlit thread gets its own connection via threading.local().
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=10,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._connect()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params_list)

    def commit(self):
        self.conn.commit()

    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def _init_schema(self):
        from database.models import CREATE_TABLES_SQL
        conn = self._connect()
        for statement in CREATE_TABLES_SQL:
            conn.execute(statement)
        conn.commit()
        logger.info("Database schema initialized at %s", self._db_path)
