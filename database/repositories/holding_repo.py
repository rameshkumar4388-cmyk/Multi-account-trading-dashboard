from __future__ import annotations

from datetime import datetime
from typing import List

from database.db import Database
from schemas.holding import Holding


class HoldingRepository:
    def __init__(self, db: Database):
        self._db = db

    def upsert_holdings(self, holdings: List[Holding]):
        for h in holdings:
            self._db.execute(
                """
                INSERT INTO holdings_cache
                    (account_id, broker, symbol, exchange, isin, quantity, avg_price,
                     ltp, current_value, invested_value, pnl, pnl_pct, sector, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, symbol) DO UPDATE SET
                    quantity=excluded.quantity,
                    avg_price=excluded.avg_price,
                    ltp=excluded.ltp,
                    current_value=excluded.current_value,
                    invested_value=excluded.invested_value,
                    pnl=excluded.pnl,
                    pnl_pct=excluded.pnl_pct,
                    sector=excluded.sector,
                    updated_at=excluded.updated_at
                """,
                (
                    h.account_id, h.broker, h.symbol, h.exchange, h.isin,
                    h.quantity, h.avg_price, h.ltp, h.current_value,
                    h.invested_value, h.pnl, h.pnl_pct, h.sector,
                    datetime.now().isoformat(),
                ),
            )
        self._db.commit()

    def get_holdings(self, account_id: str) -> List[Holding]:
        rows = self._db.fetchall(
            "SELECT * FROM holdings_cache WHERE account_id = ?", (account_id,)
        )
        holdings = []
        for r in rows:
            h = Holding(
                account_id=r["account_id"],
                broker=r["broker"],
                symbol=r["symbol"],
                exchange=r["exchange"],
                isin=r["isin"] or "",
                quantity=r["quantity"],
                avg_price=r["avg_price"],
                ltp=r["ltp"],
                sector=r["sector"] or "Unknown",
            )
            holdings.append(h)
        return holdings
