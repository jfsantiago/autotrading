from unittest.mock import MagicMock, patch

from autotrading.news.cache import get_cached_classifications, get_cached_raw, save_classifications
from autotrading.news.models import LLMClassification, SentimentLabel
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


def test_raw_cache_hit_avoids_refetch(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return {"value": 42}

    first = get_cached_raw(tmp_path, "key1", ttl_hours=1, fetch_fn=fetch)
    second = get_cached_raw(tmp_path, "key1", ttl_hours=1, fetch_fn=fetch)

    assert first == {"value": 42}
    assert second == {"value": 42}
    assert len(calls) == 1


def test_raw_cache_different_keys_both_fetch(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return {"value": len(calls)}

    get_cached_raw(tmp_path, "key1", ttl_hours=1, fetch_fn=fetch)
    get_cached_raw(tmp_path, "key2", ttl_hours=1, fetch_fn=fetch)

    assert len(calls) == 2


def test_get_cached_classifications_empty_input_skips_connection():
    with patch("autotrading.news.cache.psycopg2.connect") as mock_connect:
        result = get_cached_classifications(make_secrets(), [])
    assert result == {}
    mock_connect.assert_not_called()


def test_get_cached_classifications_parses_rows():
    cursor = MagicMock()
    cursor.fetchall.return_value = [("item-1", "bullish", 0.9, ["BTC"])]
    conn = make_mock_conn(cursor)

    with patch("autotrading.news.cache.psycopg2.connect", return_value=conn):
        result = get_cached_classifications(make_secrets(), ["item-1", "item-2"])

    cursor.execute.assert_called_once()
    query, params = cursor.execute.call_args.args
    assert params == (["item-1", "item-2"],)
    assert result["item-1"].label == SentimentLabel.BULLISH
    assert result["item-1"].confidence == 0.9
    assert result["item-1"].relevant_symbols == ["BTC"]
    assert "item-2" not in result


def test_save_classifications_empty_input_skips_connection():
    with patch("autotrading.news.cache.psycopg2.connect") as mock_connect:
        save_classifications(make_secrets(), {})
    mock_connect.assert_not_called()


def test_save_classifications_upserts_via_execute_values():
    cursor = MagicMock()
    conn = make_mock_conn(cursor)
    classification = LLMClassification(
        label=SentimentLabel.BEARISH, confidence=0.7, relevant_symbols=["ETH"]
    )

    with (
        patch("autotrading.news.cache.psycopg2.connect", return_value=conn),
        patch("autotrading.news.cache.execute_values") as mock_execute_values,
    ):
        save_classifications(make_secrets(), {"item-1": classification})

    mock_execute_values.assert_called_once()
    _, args, _ = mock_execute_values.mock_calls[0]
    rows = args[2]
    assert rows == [("item-1", "bearish", 0.7, '["ETH"]')]
    conn.commit.assert_called_once()
