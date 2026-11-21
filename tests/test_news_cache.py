from autotrading.news.cache import get_cached_classification, get_cached_raw, save_classification
from autotrading.news.models import LLMClassification, SentimentLabel


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


def test_classification_cache_roundtrip(tmp_path):
    assert get_cached_classification(tmp_path, "item-1") is None

    classification = LLMClassification(
        label=SentimentLabel.BULLISH, confidence=0.9, relevant_symbols=["BTC"]
    )
    save_classification(tmp_path, "item-1", classification)

    cached = get_cached_classification(tmp_path, "item-1")
    assert cached.label == SentimentLabel.BULLISH
    assert cached.confidence == 0.9
    assert cached.relevant_symbols == ["BTC"]
