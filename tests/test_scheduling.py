from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from autotrading.scheduling import (
    BotState,
    ensure_bot_state_row,
    fetch_bot_state,
    is_due,
    mark_run_completed,
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
    cursor.fetchone.return_value = (True, 45, last_run)
    conn = make_mock_conn(cursor)

    with patch("autotrading.scheduling.psycopg2.connect", return_value=conn):
        state = fetch_bot_state(make_secrets())

    assert state.bot_enabled is True
    assert state.run_interval_minutes == 45
    assert state.last_run_at == last_run


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
