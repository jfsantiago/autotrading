import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from autotrading.news.config import (
    CalendarConfig,
    NewsCacheConfig,
    NewsConfig,
    NewsDataConfig,
    NewsOutputConfig,
    RssConfig,
    SentimentConfig,
)
from autotrading.news.models import NewsItem
from autotrading.news.pipeline import build_news_snapshot
from autotrading.secrets import Secrets


def make_news_config(tmp_path, macro_file):
    return NewsConfig(
        rss=RssConfig(feeds=["http://fake-feed"], fetch_limit_per_feed=10),
        newsdata=NewsDataConfig(enabled=False, source_weight=1.0),
        sentiment=SentimentConfig(llm_model="fake-model", llm_batch_size=10, llm_source_weight=1.0),
        calendar=CalendarConfig(
            crypto_events_enabled=False,
            lookahead_days=14,
            macro_events_file=str(macro_file),
            soon_threshold_days=3,
        ),
        cache=NewsCacheConfig(dir=str(tmp_path / "cache"), raw_ttl_hours=6),
        output=NewsOutputConfig(dir=str(tmp_path / "out"), save_csv=False),
    )


def make_app_config(tmp_path, macro_file):
    return SimpleNamespace(
        all_symbols=["BTC/USDT"],
        news=make_news_config(tmp_path, macro_file),
    )


def make_secrets():
    return Secrets(
        openai_api_key="fake-key",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
    )


def fake_chat_response(classifications):
    content = json.dumps({"classifications": classifications})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_build_news_snapshot_end_to_end(tmp_path):
    macro_file = tmp_path / "macro.yaml"
    macro_file.write_text("events: []\n")
    config = make_app_config(tmp_path, macro_file)
    secrets = make_secrets()

    rss_item = NewsItem(
        item_id="item-1",
        source="fake",
        title="Bitcoin rallies",
        link="http://x/1",
        published_at=datetime.now(timezone.utc),
    )

    fake_openai_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: fake_chat_response(
                    [{"id": "item-1", "label": "bullish", "confidence": 0.9, "relevant_symbols": ["BTC"]}]
                )
            )
        )
    )

    with (
        patch("autotrading.news.pipeline.fetch_rss_items", return_value=[rss_item]),
        patch("openai.OpenAI", return_value=fake_openai_client),
        patch(
            "autotrading.news.llm_sentiment.news_cache.get_cached_classifications",
            return_value={},
        ),
        patch("autotrading.news.llm_sentiment.news_cache.save_classifications"),
    ):
        snapshot = build_news_snapshot(config, secrets)

    assert len(snapshot.scored_items) == 1
    assert snapshot.symbol_sentiments["BTC/USDT"].average_score == 1.0
    assert snapshot.upcoming_events == []
