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
    leverage: int | None = None  # None = no override, use YAML/env value
    position_size_pct: float | None = None  # None = no override, use YAML/env value
    take_profit_margin_pct: float | None = None  # None = no override, use YAML value


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
            "SELECT bot_enabled, run_interval_minutes, last_run_at, leverage, "
            "position_size_pct, take_profit_margin_pct FROM bot_state WHERE id = %s",
            (BOT_STATE_ROW_ID,),
        )
        (
            bot_enabled, run_interval_minutes, last_run_at, leverage,
            position_size_pct, take_profit_margin_pct,
        ) = cur.fetchone()
    return BotState(
        bot_enabled=bot_enabled,
        run_interval_minutes=run_interval_minutes,
        last_run_at=last_run_at,
        leverage=leverage,
        position_size_pct=position_size_pct,
        take_profit_margin_pct=take_profit_margin_pct,
    )


def mark_run_completed(secrets: Secrets, when: datetime) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_state SET last_run_at = %s WHERE id = %s",
            (when, BOT_STATE_ROW_ID),
        )
        conn.commit()


def set_leverage(secrets: Secrets, value: int | None) -> None:
    """Range validation (assert_leverage_safe) is the caller's job — this
    module is deliberately pure Supabase I/O, same reasoning as every other
    function here, so a bad value never silently lands without a check."""
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute("UPDATE bot_state SET leverage = %s WHERE id = %s", (value, BOT_STATE_ROW_ID))
        conn.commit()


def set_position_size_pct(secrets: Secrets, value: float | None) -> None:
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_state SET position_size_pct = %s WHERE id = %s",
            (value, BOT_STATE_ROW_ID),
        )
        conn.commit()


def set_take_profit_margin_pct(secrets: Secrets, value: float | None) -> None:
    """stop_loss_margin_pct is always derived as half of this (see
    RiskParameters.stop_loss_margin_pct) — there's no separate setter for
    it, so the ratio can never drift out of sync via two independent calls.
    """
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_state SET take_profit_margin_pct = %s WHERE id = %s",
            (value, BOT_STATE_ROW_ID),
        )
        conn.commit()


def set_bot_enabled(secrets: Secrets, enabled: bool) -> None:
    """The emergency kill switch: run_scheduled_command checks this before
    doing anything else, so flipping it to False stops the next heartbeat
    from making any API calls at all, not just from placing orders. Does
    NOT touch positions already open — those keep whatever stop-loss is
    already resting on Binance regardless of whether this process is
    running.
    """
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_state SET bot_enabled = %s WHERE id = %s", (enabled, BOT_STATE_ROW_ID)
        )
        conn.commit()


def is_due(state: BotState, now: datetime) -> bool:
    if state.last_run_at is None:
        return True
    return (now - state.last_run_at) >= timedelta(minutes=state.run_interval_minutes)
