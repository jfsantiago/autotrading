from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg2

from autotrading.secrets import Secrets


@dataclass
class TrackedPosition:
    symbol: str
    position_side: str
    quantity: float
    entry_price: float
    opened_at: datetime


def track_open_position(
    secrets: Secrets,
    *,
    symbol: str,
    position_side: str,
    quantity: float,
    entry_price: float,
) -> None:
    """Record that WE opened this position, so a later review can notice if
    Binance shows it flat without us having closed it (a stop-loss fired).
    Upsert: also used to self-heal/bootstrap tracking for a position that
    already existed before this feature was added.
    """
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO open_position_tracking "
            "(symbol, position_side, quantity, entry_price) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (symbol) DO UPDATE SET "
            "position_side = EXCLUDED.position_side, quantity = EXCLUDED.quantity, "
            "entry_price = EXCLUDED.entry_price, opened_at = now()",
            (symbol, position_side, quantity, entry_price),
        )
        conn.commit()


def untrack_position(secrets: Secrets, symbol: str) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM open_position_tracking WHERE symbol = %s", (symbol,))
        conn.commit()


def fetch_all_tracked_positions(secrets: Secrets) -> dict[str, TrackedPosition]:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, position_side, quantity, entry_price, opened_at "
            "FROM open_position_tracking"
        )
        rows = cur.fetchall()
    return {row[0]: TrackedPosition(*row) for row in rows}
