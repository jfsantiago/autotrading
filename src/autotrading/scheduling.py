from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg2

from autotrading.secrets import Secrets

BOT_STATE_ROW_ID = 1
DEFAULT_RUN_INTERVAL_MINUTES = 60


@dataclass
class BotState:
    bot_enabled: bool
    run_interval_minutes: int
    last_run_at: datetime | None


def ensure_bot_state_row(secrets: Secrets) -> None:
    """Self-creates the singleton bot_state row on first use, with safe
    defaults (bot disabled, 60-minute interval) — no manual setup needed.
    """
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_state (id, bot_enabled, run_interval_minutes) "
            "VALUES (%s, false, %s) ON CONFLICT (id) DO NOTHING",
            (BOT_STATE_ROW_ID, DEFAULT_RUN_INTERVAL_MINUTES),
        )
        conn.commit()


def fetch_bot_state(secrets: Secrets) -> BotState:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT bot_enabled, run_interval_minutes, last_run_at "
            "FROM bot_state WHERE id = %s",
            (BOT_STATE_ROW_ID,),
        )
        bot_enabled, run_interval_minutes, last_run_at = cur.fetchone()
    return BotState(
        bot_enabled=bot_enabled,
        run_interval_minutes=run_interval_minutes,
        last_run_at=last_run_at,
    )


def mark_run_completed(secrets: Secrets, when: datetime) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_state SET last_run_at = %s WHERE id = %s",
            (when, BOT_STATE_ROW_ID),
        )
        conn.commit()


def is_due(state: BotState, now: datetime) -> bool:
    if state.last_run_at is None:
        return True
    return (now - state.last_run_at) >= timedelta(minutes=state.run_interval_minutes)
