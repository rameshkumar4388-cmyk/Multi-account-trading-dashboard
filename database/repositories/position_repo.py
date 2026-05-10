from __future__ import annotations

from datetime import datetime
from typing import List

from database.db import Database
from schemas.position import Position


class PositionRepository:
    def __init__(self, db: Database):
        self._db = db

    def upsert_positions(self, positions: List[Position]):
        for p in positions:
            self._db.execute(
                """
                INSERT INTO positions_cache
                    (account_id, broker, symbol, exchange, product, instrument_type,
                     quantity, avg_price, ltp, pnl, day_pnl, value,
                     expiry, strike, lot_size, underlying, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, symbol, product) DO UPDATE SET
                    quantity=excluded.quantity,
                    avg_price=excluded.avg_price,
                    ltp=excluded.ltp,
                    pnl=excluded.pnl,
                    day_pnl=excluded.day_pnl,
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (
                    p.account_id, p.broker, p.symbol, p.exchange,
                    p.product, p.instrument_type, p.quantity, p.avg_price,
                    p.ltp, p.pnl, p.day_pnl, p.value,
                    p.expiry, p.strike, p.lot_size, p.underlying,
                    datetime.now().isoformat(),
                ),
            )
        self._db.commit()

    def get_positions(self, account_id: str) -> List[Position]:
        rows = self._db.fetchall(
            "SELECT * FROM positions_cache WHERE account_id = ?", (account_id,)
        )
        positions = []
        for r in rows:
            p = Position(
                account_id=r["account_id"],
                broker=r["broker"],
                symbol=r["symbol"],
                exchange=r["exchange"],
                product=r["product"],
                instrument_type=r["instrument_type"],
                quantity=r["quantity"],
                avg_price=r["avg_price"],
                ltp=r["ltp"],
                pnl=r["pnl"],
                day_pnl=r["day_pnl"],
                value=r["value"],
                lot_size=r["lot_size"],
                expiry=r["expiry"],
                strike=r["strike"],
                underlying=r["underlying"] or r["symbol"],
            )
            positions.append(p)
        return positions
