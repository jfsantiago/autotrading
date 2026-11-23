from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg2

from autotrading.secrets import Secrets


@dataclass
class ClosedTrade:
    symbol: str
    position_side: str
    quantity: float
    entry_price: float
    exit_price: float | None
    realized_pnl: float | None
    closed_at: datetime


def record_closed_trade(
    secrets: Secrets,
    *,
    symbol: str,
    position_side: str,
    quantity: float,
    entry_price: float,
    exit_price: float | None,
    realized_pnl: float | None,
) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO closed_trades "
            "(symbol, position_side, quantity, entry_price, exit_price, realized_pnl) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (symbol, position_side, quantity, entry_price, exit_price, realized_pnl),
        )
        conn.commit()


def fetch_recent_closed_trades(secrets: Secrets, limit: int = 10) -> list[ClosedTrade]:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, position_side, quantity, entry_price, exit_price, "
            "realized_pnl, closed_at FROM closed_trades ORDER BY closed_at DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return [ClosedTrade(*row) for row in rows]
