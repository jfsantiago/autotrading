from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autotrading.config import AppConfig
from autotrading.news.aggregate import aggregate_by_symbol
from autotrading.news.events import merge_events
from autotrading.news.llm_sentiment import classify_headlines_batch
from autotrading.news.macro_calendar import load_macro_events
from autotrading.news.models import ScoredItem, SymbolSentiment, UpcomingEvent
from autotrading.news.scoring import label_to_score
from autotrading.news.sources.coinmarketcal import fetch_crypto_events
from autotrading.news.sources.newsdata import fetch_newsdata_items
from autotrading.news.sources.rss import fetch_rss_items
from autotrading.secrets import Secrets


@dataclass
class NewsSnapshot:
    scored_items: list[ScoredItem]
    symbol_sentiments: dict[str, SymbolSentiment]
    upcoming_events: list[UpcomingEvent]


def build_news_snapshot(config: AppConfig, secrets: Secrets) -> NewsSnapshot:
    """Fetch RSS + optional sources, classify via LLM, score, aggregate per
    symbol, and merge upcoming events. Caller must ensure config.news is not
    None before calling this.
    """
    import openai

    news_cfg = config.news
    cache_dir = Path(news_cfg.cache.dir)

    rss_items = fetch_rss_items(news_cfg.rss.feeds, news_cfg.rss.fetch_limit_per_feed)

    newsdata_items = []
    if news_cfg.newsdata.enabled:
        newsdata_items = fetch_newsdata_items(
            secrets, config.all_symbols, cache_dir, news_cfg.cache.raw_ttl_hours
        )

    crypto_events = []
    if news_cfg.calendar.crypto_events_enabled:
        crypto_events = fetch_crypto_events(
            secrets,
            config.all_symbols,
            news_cfg.calendar.lookahead_days,
            cache_dir,
            news_cfg.cache.raw_ttl_hours,
        )
    macro_events = load_macro_events(news_cfg.calendar.macro_events_file)

    client = openai.OpenAI(api_key=secrets.openai_api_key)
    classifications = classify_headlines_batch(
        client,
        rss_items,
        config.all_symbols,
        cache_dir,
        news_cfg.sentiment.llm_model,
        news_cfg.sentiment.llm_batch_size,
    )

    scored_items: list[ScoredItem] = []
    for item in rss_items:
        classification = classifications[item.item_id]
        scored_items.append(
            ScoredItem(
                item=item,
                label=classification.label,
                score=label_to_score(classification.label),
                symbols=classification.relevant_symbols,
                source_weight=news_cfg.sentiment.llm_source_weight,
            )
        )
    for item in newsdata_items:
        label = item.native_label
        scored_items.append(
            ScoredItem(
                item=item,
                label=label,
                score=label_to_score(label),
                symbols=item.native_symbols or [],
                source_weight=news_cfg.newsdata.source_weight,
            )
        )

    symbol_sentiments = aggregate_by_symbol(scored_items, config.all_symbols)
    upcoming_events = merge_events(
        crypto_events, macro_events, news_cfg.calendar.soon_threshold_days
    )

    return NewsSnapshot(
        scored_items=scored_items,
        symbol_sentiments=symbol_sentiments,
        upcoming_events=upcoming_events,
    )
