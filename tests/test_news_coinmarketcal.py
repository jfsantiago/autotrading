from unittest.mock import MagicMock, patch

from autotrading.news.sources.coinmarketcal import fetch_crypto_events
from autotrading.secrets import Secrets


def make_secrets(cmc_key="key123"):
    return Secrets(
        openai_api_key="openai-key", newsdata_api_key=None, coinmarketcal_api_key=cmc_key
    )


def test_no_api_key_degrades_to_empty_list(tmp_path):
    secrets = make_secrets(cmc_key=None)
    events = fetch_crypto_events(secrets, ["BTC/USDT"], 14, tmp_path, ttl_hours=1)
    assert events == []


def test_fetch_crypto_events_parses_events(tmp_path):
    secrets = make_secrets()
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "body": [
            {
                "date_event": "2026-02-01T00:00:00.000Z",
                "title": {"en": "Token unlock"},
                "coins": [{"symbol": "btc"}],
            }
        ]
    }
    fake_response.raise_for_status.return_value = None

    with patch(
        "autotrading.news.sources.coinmarketcal.requests.get", return_value=fake_response
    ):
        events = fetch_crypto_events(secrets, ["BTC/USDT"], 14, tmp_path, ttl_hours=1)

    assert len(events) == 1
    assert events[0].date == "2026-02-01"
    assert events[0].title == "Token unlock"
    assert events[0].symbol == "BTC"


def test_fetch_crypto_events_request_failure_degrades_to_empty(tmp_path):
    secrets = make_secrets()
    with patch(
        "autotrading.news.sources.coinmarketcal.requests.get",
        side_effect=Exception("network down"),
    ):
        events = fetch_crypto_events(secrets, ["BTC/USDT"], 14, tmp_path, ttl_hours=1)
    assert events == []
