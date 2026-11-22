from unittest.mock import MagicMock, patch

from autotrading.news.sources.newsdata import fetch_newsdata_items
from autotrading.news.models import SentimentLabel
from autotrading.secrets import Secrets


def make_secrets(newsdata_key="key123"):
    return Secrets(
        openai_api_key="openai-key",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=newsdata_key,
        coinmarketcal_api_key=None,
    )


def test_no_api_key_degrades_to_empty_list(tmp_path):
    secrets = make_secrets(newsdata_key=None)
    items = fetch_newsdata_items(secrets, ["BTC/USDT"], tmp_path, ttl_hours=1)
    assert items == []


def test_fetch_newsdata_parses_items(tmp_path):
    secrets = make_secrets()
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "results": [
            {
                "title": "Bitcoin surges",
                "link": "http://example.com/a",
                "pubDate": "2024-01-01T00:00:00Z",
                "sentiment": "positive",
                "coin": ["btc"],
            }
        ]
    }
    fake_response.raise_for_status.return_value = None

    with patch("autotrading.news.sources.newsdata.requests.get", return_value=fake_response):
        items = fetch_newsdata_items(secrets, ["BTC/USDT"], tmp_path, ttl_hours=1)

    assert len(items) == 1
    assert items[0].title == "Bitcoin surges"
    assert items[0].native_label == SentimentLabel.BULLISH
    assert items[0].native_symbols == ["BTC"]


def test_fetch_newsdata_request_failure_degrades_to_empty(tmp_path):
    secrets = make_secrets()
    with patch(
        "autotrading.news.sources.newsdata.requests.get", side_effect=Exception("network down")
    ):
        items = fetch_newsdata_items(secrets, ["BTC/USDT"], tmp_path, ttl_hours=1)
    assert items == []
