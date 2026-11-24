from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from autotrading.scheduling import (
    BotState,
    assert_run_interval_safe,
    ensure_bot_state_row,
    fetch_bot_state,
    is_due,
    mark_run_completed,
    set_bot_enabled,
    set_leverage,
    set_position_size_pct,
    set_run_interval_minutes,
    set_take_profit_margin_pct,
)
from autotrading.secrets import Secrets


def make_secrets():
    return Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
    )


def make_mock_conn(cursor):
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = cursor
    return mock_conn


def test_is_due_when_never_run():
    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=None)
    assert is_due(state, datetime.now(timezone.utc)) is True


def test_is_due_false_when_interval_not_elapsed():
    now = datetime.now(timezone.utc)
    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(minutes=30))
    assert is_due(state, now) is False


def test_is_due_true_when_interval_elapsed():
    now = datetime.now(timezone.utc)
    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(minutes=61))
    assert is_due(state, now) is True


def test_is_due_boundary_exactly_at_interval():
    now = datetime.now(timezone.utc)
    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(minutes=60))
    assert is_due(state, now) is True


def test_ensure_bot_state_row_issues_insert_on_conflict_do_nothing():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        ensure_bot_state_row(make_secrets())

    query = cursor.execute.call_args.args[0]
    assert "INSERT INTO bot_state" in query
    assert "ON CONFLICT (id) DO NOTHING" in query
    conn.commit.assert_called_once()


def test_fetch_bot_state_parses_row():
    cursor = MagicMock()
    last_run = datetime.now(timezone.utc)
    cursor.fetchone.return_value = (True, 45, last_run, 7, 0.1, 0.2)
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        state = fetch_bot_state(make_secrets())

    assert state.bot_enabled is True
    assert state.run_interval_minutes == 45
    assert state.last_run_at == last_run
    assert state.leverage == 7
    assert state.position_size_pct == 0.1
    assert state.take_profit_margin_pct == 0.2


def test_fetch_bot_state_leverage_and_risk_default_to_none():
    cursor = MagicMock()
    cursor.fetchone.return_value = (True, 60, None, None, None, None)
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        state = fetch_bot_state(make_secrets())

    assert state.leverage is None
    assert state.position_size_pct is None
    assert state.take_profit_margin_pct is None


def test_mark_run_completed_updates_last_run_at():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)
    when = datetime.now(timezone.utc)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        mark_run_completed(make_secrets(), when)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query
    assert params[0] == when
    conn.commit.assert_called_once()


def test_set_leverage_updates_column():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_leverage(make_secrets(), 7)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query and "leverage" in query
    assert params == (7, 1)
    conn.commit.assert_called_once()


def test_set_leverage_can_clear_override_with_none():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_leverage(make_secrets(), None)

    _, params = cursor.execute.call_args.args
    assert params[0] is None


def test_set_position_size_pct_updates_column():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_position_size_pct(make_secrets(), 0.1)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query and "position_size_pct" in query
    assert params == (0.1, 1)
    conn.commit.assert_called_once()


def test_set_take_profit_margin_pct_updates_column():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_take_profit_margin_pct(make_secrets(), 0.2)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query and "take_profit_margin_pct" in query
    assert params == (0.2, 1)
    conn.commit.assert_called_once()


def test_set_bot_enabled_updates_column():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_bot_enabled(make_secrets(), False)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query and "bot_enabled" in query
    assert params == (False, 1)
    conn.commit.assert_called_once()


def test_set_run_interval_minutes_updates_column():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        set_run_interval_minutes(make_secrets(), 30)

    query, params = cursor.execute.call_args.args
    assert "UPDATE bot_state" in query and "run_interval_minutes" in query
    assert params == (30, 1)
    conn.commit.assert_called_once()


@pytest.mark.parametrize("minutes", [5, 60, 1440])
def test_assert_run_interval_safe_accepts_in_range(minutes):
    assert_run_interval_safe(minutes)  # should not raise


@pytest.mark.parametrize("minutes", [0, 4, -5, 1441, 100000])
def test_assert_run_interval_safe_rejects_out_of_range(minutes):
    with pytest.raises(ValueError):
        assert_run_interval_safe(minutes)
