from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from autotrading.position_tracking import (
    fetch_all_tracked_positions,
    track_open_position,
    untrack_position,
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


def test_track_open_position_upserts_expected_row():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.position_tracking.psycopg2.connect", return_value=conn):
        track_open_position(
            make_secrets(),
            symbol="BTC/USDT",
            position_side="long",
            quantity=1.5,
            entry_price=50000.0,
        )

    query, params = cursor.execute.call_args.args
    assert "INSERT INTO open_position_tracking" in query
    assert "ON CONFLICT (symbol) DO UPDATE" in query
    assert params == ("BTC/USDT", "long", 1.5, 50000.0)
    conn.commit.assert_called_once()


def test_untrack_position_deletes_by_symbol():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.position_tracking.psycopg2.connect", return_value=conn):
        untrack_position(make_secrets(), "BTC/USDT")

    query, params = cursor.execute.call_args.args
    assert "DELETE FROM open_position_tracking" in query
    assert params == ("BTC/USDT",)
    conn.commit.assert_called_once()


def test_fetch_all_tracked_positions_parses_rows_into_dict():
    cursor = MagicMock()
    opened_at = datetime.now(timezone.utc)
    cursor.fetchall.return_value = [
        ("BTC/USDT", "long", 1.5, 50000.0, opened_at),
        ("ETH/USDT", "short", 2.0, 3000.0, opened_at),
    ]
    conn = make_mock_conn(cursor)

    with patch("autotrading.position_tracking.psycopg2.connect", return_value=conn):
        tracked = fetch_all_tracked_positions(make_secrets())

    assert set(tracked.keys()) == {"BTC/USDT", "ETH/USDT"}
    assert tracked["BTC/USDT"].position_side == "long"
    assert tracked["BTC/USDT"].entry_price == 50000.0
    assert tracked["ETH/USDT"].quantity == 2.0
