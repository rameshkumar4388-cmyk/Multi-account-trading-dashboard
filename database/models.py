"""
SQLite DDL — all table definitions.
Imported by db.py during initialization.
"""

CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        account_id   TEXT PRIMARY KEY,
        broker       TEXT NOT NULL,
        display_name TEXT NOT NULL,
        owner        TEXT NOT NULL,
        user_id      TEXT,
        email        TEXT,
        is_active    INTEGER DEFAULT 1,
        updated_at   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS holdings_cache (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id   TEXT NOT NULL,
        broker       TEXT NOT NULL,
        symbol       TEXT NOT NULL,
        exchange     TEXT NOT NULL,
        isin         TEXT,
        quantity     INTEGER NOT NULL,
        avg_price    REAL NOT NULL,
        ltp          REAL DEFAULT 0,
        current_value REAL DEFAULT 0,
        invested_value REAL DEFAULT 0,
        pnl          REAL DEFAULT 0,
        pnl_pct      REAL DEFAULT 0,
        sector       TEXT,
        updated_at   TEXT,
        UNIQUE(account_id, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions_cache (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id       TEXT NOT NULL,
        broker           TEXT NOT NULL,
        symbol           TEXT NOT NULL,
        exchange         TEXT NOT NULL,
        product          TEXT NOT NULL,
        instrument_type  TEXT NOT NULL,
        quantity         INTEGER NOT NULL,
        avg_price        REAL NOT NULL,
        ltp              REAL DEFAULT 0,
        pnl              REAL DEFAULT 0,
        day_pnl          REAL DEFAULT 0,
        value            REAL DEFAULT 0,
        expiry           TEXT,
        strike           REAL,
        lot_size         INTEGER DEFAULT 1,
        underlying       TEXT,
        updated_at       TEXT,
        UNIQUE(account_id, symbol, product)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS margin_cache (
        account_id       TEXT PRIMARY KEY,
        broker           TEXT NOT NULL,
        available_cash   REAL DEFAULT 0,
        used_margin      REAL DEFAULT 0,
        span_margin      REAL DEFAULT 0,
        exposure_margin  REAL DEFAULT 0,
        total_collateral REAL DEFAULT 0,
        net_available    REAL DEFAULT 0,
        updated_at       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pnl_snapshots (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id   TEXT NOT NULL,
        snap_date    TEXT NOT NULL,
        holdings_pnl REAL DEFAULT 0,
        positions_pnl REAL DEFAULT 0,
        day_pnl      REAL DEFAULT 0,
        net_worth    REAL DEFAULT 0,
        recorded_at  TEXT,
        UNIQUE(account_id, snap_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS refresh_log (
        account_id   TEXT NOT NULL,
        data_type    TEXT NOT NULL,
        refreshed_at TEXT NOT NULL,
        PRIMARY KEY (account_id, data_type)
    )
    """,
]
