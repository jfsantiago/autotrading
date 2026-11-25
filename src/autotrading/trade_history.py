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
    closed_via: str
    margin: float | None
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
    closed_via: str = "bot",
    margin: float | None = None,
) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO closed_trades "
            "(symbol, position_side, quantity, entry_price, exit_price, realized_pnl, "
            "closed_via, margin) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                symbol, position_side, quantity, entry_price, exit_price, realized_pnl,
                closed_via, margin,
            ),
        )
        conn.commit()


def fetch_recent_closed_trades(secrets: Secrets, limit: int = 10) -> list[ClosedTrade]:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, position_side, quantity, entry_price, exit_price, "
            "realized_pnl, closed_via, margin, closed_at FROM closed_trades "
            "ORDER BY closed_at DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return [ClosedTrade(*row) for row in rows]


def fetch_closed_trades_totals(secrets: Secrets) -> tuple[int, float, float]:
    """Aggregates over ALL closed trades ever, not just whatever page
    /history happens to display — so a long history doesn't silently make
    the on-screen total look better than reality just because older losing
    trades scrolled out of the displayed window. SUM() in Postgres already
    skips NULL margin values on its own, no need to filter them out here.
    """
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(margin), 0), COALESCE(SUM(realized_pnl), 0) "
            "FROM closed_trades"
        )
        count, total_margin, total_pnl = cur.fetchone()
    return count, total_margin, total_pnl
