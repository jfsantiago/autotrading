import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from autotrading.news.llm_sentiment import classify_headlines_batch
from autotrading.news.models import NewsItem, SentimentLabel
from autotrading.secrets import Secrets


def make_item(item_id):
    return NewsItem(
        item_id=item_id,
        source="test",
        title=f"headline {item_id}",
        link=f"http://x/{item_id}",
        published_at=datetime.now(timezone.utc),
    )


def make_chat_completion_response(classifications):
    content = json.dumps({"classifications": classifications})
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.call_count += 1
        return self._responses.pop(0)


def make_secrets():
    return Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
    )


def fake_cache_backend(store: dict):
    """In-memory stand-in for the Supabase-backed classification cache, so
    tests can verify cache-hit behavior across calls without a real DB.
    """

    def get_cached(secrets, item_ids):
        return {item_id: store[item_id] for item_id in item_ids if item_id in store}

    def save(secrets, classifications):
        store.update(classifications)

    return get_cached, save


def test_classify_batches_calls():
    items = [make_item("a"), make_item("b"), make_item("c")]
    responses = [
        make_chat_completion_response(
            [
                {"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": ["BTC"]},
                {"id": "b", "label": "bearish", "confidence": 0.8, "relevant_symbols": []},
            ]
        ),
        make_chat_completion_response(
            [{"id": "c", "label": "neutral", "confidence": 0.5, "relevant_symbols": []}]
        ),
    ]
    client = FakeClient(responses)
    get_cached, save = fake_cache_backend({})

    with (
        patch("autotrading.news.llm_sentiment.news_cache.get_cached_classifications", get_cached),
        patch("autotrading.news.llm_sentiment.news_cache.save_classifications", save),
    ):
        results = classify_headlines_batch(
            client, items, ["BTC/USDT"], make_secrets(), model="fake-model", batch_size=2
        )

    assert client.call_count == 2
    assert results["a"].label == SentimentLabel.BULLISH
    assert results["b"].label == SentimentLabel.BEARISH
    assert results["c"].label == SentimentLabel.NEUTRAL


def test_classify_uses_cache_on_second_call():
    items = [make_item("a")]
    responses = [
        make_chat_completion_response(
            [{"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": ["BTC"]}]
        )
    ]
    client = FakeClient(responses)
    store: dict = {}
    get_cached, save = fake_cache_backend(store)

    with (
        patch("autotrading.news.llm_sentiment.news_cache.get_cached_classifications", get_cached),
        patch("autotrading.news.llm_sentiment.news_cache.save_classifications", save),
    ):
        classify_headlines_batch(client, items, ["BTC/USDT"], make_secrets(), "fake-model", 10)
        results = classify_headlines_batch(client, items, ["BTC/USDT"], make_secrets(), "fake-model", 10)

    assert client.call_count == 1  # second call served entirely from cache
    assert results["a"].label == SentimentLabel.BULLISH


def test_classify_falls_back_to_neutral_on_missing_id():
    items = [make_item("a"), make_item("b")]
    responses = [
        make_chat_completion_response(
            [{"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": []}]
        )
    ]
    client = FakeClient(responses)
    get_cached, save = fake_cache_backend({})

    with (
        patch("autotrading.news.llm_sentiment.news_cache.get_cached_classifications", get_cached),
        patch("autotrading.news.llm_sentiment.news_cache.save_classifications", save),
    ):
        results = classify_headlines_batch(client, items, ["BTC/USDT"], make_secrets(), "fake-model", 10)

    assert results["a"].label == SentimentLabel.BULLISH
    assert results["b"].label == SentimentLabel.NEUTRAL
    assert results["b"].confidence == 0.0
