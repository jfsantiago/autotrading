from datetime import datetime, timezone
from types import SimpleNamespace

from autotrading.news.llm_sentiment import classify_headlines_batch
from autotrading.news.models import NewsItem, SentimentLabel


def make_item(item_id):
    return NewsItem(
        item_id=item_id,
        source="test",
        title=f"headline {item_id}",
        link=f"http://x/{item_id}",
        published_at=datetime.now(timezone.utc),
    )


def make_tool_use_response(classifications):
    block = SimpleNamespace(
        type="tool_use",
        name="submit_classifications",
        input={"classifications": classifications},
    )
    return SimpleNamespace(content=[block])


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.call_count += 1
        return self._responses.pop(0)


def test_classify_batches_calls(tmp_path):
    items = [make_item("a"), make_item("b"), make_item("c")]
    responses = [
        make_tool_use_response(
            [
                {"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": ["BTC"]},
                {"id": "b", "label": "bearish", "confidence": 0.8, "relevant_symbols": []},
            ]
        ),
        make_tool_use_response(
            [{"id": "c", "label": "neutral", "confidence": 0.5, "relevant_symbols": []}]
        ),
    ]
    client = FakeClient(responses)

    results = classify_headlines_batch(
        client, items, ["BTC/USDT"], tmp_path, model="fake-model", batch_size=2
    )

    assert client.call_count == 2
    assert results["a"].label == SentimentLabel.BULLISH
    assert results["b"].label == SentimentLabel.BEARISH
    assert results["c"].label == SentimentLabel.NEUTRAL


def test_classify_uses_cache_on_second_call(tmp_path):
    items = [make_item("a")]
    responses = [
        make_tool_use_response(
            [{"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": ["BTC"]}]
        )
    ]
    client = FakeClient(responses)

    classify_headlines_batch(client, items, ["BTC/USDT"], tmp_path, "fake-model", 10)
    results = classify_headlines_batch(client, items, ["BTC/USDT"], tmp_path, "fake-model", 10)

    assert client.call_count == 1  # second call served entirely from cache
    assert results["a"].label == SentimentLabel.BULLISH


def test_classify_falls_back_to_neutral_on_missing_id(tmp_path):
    items = [make_item("a"), make_item("b")]
    responses = [
        make_tool_use_response(
            [{"id": "a", "label": "bullish", "confidence": 0.9, "relevant_symbols": []}]
        )
    ]
    client = FakeClient(responses)

    results = classify_headlines_batch(client, items, ["BTC/USDT"], tmp_path, "fake-model", 10)

    assert results["a"].label == SentimentLabel.BULLISH
    assert results["b"].label == SentimentLabel.NEUTRAL
    assert results["b"].confidence == 0.0
