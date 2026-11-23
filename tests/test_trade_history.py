from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from autotrading.secrets import Secrets
from autotrading.trade_history import fetch_recent_closed_trades, record_closed_trade


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


def test_record_closed_trade_inserts_expected_row():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)

    with patch("autotrading.trade_history.psycopg2.connect", return_value=conn):
        record_closed_trade(
            make_secrets(),
            symbol="BTC/USDT",
            position_side="long",
            quantity=1.5,
            entry_price=50000.0,
            exit_price=51000.0,
            realized_pnl=1500.0,
        )

    query, params = cursor.execute.call_args.args
    assert "INSERT INTO closed_trades" in query
    assert params == ("BTC/USDT", "long", 1.5, 50000.0, 51000.0, 1500.0)
    conn.commit.assert_called_once()


def test_fetch_recent_closed_trades_parses_rows():
    cursor = MagicMock()
    closed_at = datetime.now(timezone.utc)
    cursor.fetchall.return_value = [
        ("BTC/USDT", "long", 1.5, 50000.0, 51000.0, 1500.0, closed_at)
    ]
    conn = make_mock_conn(cursor)

    with patch("autotrading.trade_history.psycopg2.connect", return_value=conn):
        trades = fetch_recent_closed_trades(make_secrets(), limit=5)

    query, params = cursor.execute.call_args.args
    assert "SELECT" in query and "ORDER BY closed_at DESC LIMIT %s" in query
    assert params == (5,)
    assert len(trades) == 1
    assert trades[0].symbol == "BTC/USDT"
    assert trades[0].realized_pnl == 1500.0
    assert trades[0].closed_at == closed_at
