from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RssConfig:
    feeds: list[str]
    fetch_limit_per_feed: int


@dataclass
class NewsDataConfig:
    enabled: bool
    source_weight: float


@dataclass
class SentimentConfig:
    llm_model: str
    llm_batch_size: int
    llm_source_weight: float


@dataclass
class CalendarConfig:
    crypto_events_enabled: bool
    lookahead_days: int
    macro_events_file: str
    soon_threshold_days: int


@dataclass
class NewsCacheConfig:
    dir: str
    raw_ttl_hours: int


@dataclass
class NewsOutputConfig:
    dir: str
    save_csv: bool


@dataclass
class NewsConfig:
    rss: RssConfig
    newsdata: NewsDataConfig
    sentiment: SentimentConfig
    calendar: CalendarConfig
    cache: NewsCacheConfig
    output: NewsOutputConfig


def load_news_config(raw: dict[str, Any] | None) -> NewsConfig | None:
    if raw is None:
        return None

    rss = raw["rss"]
    newsdata = raw["newsdata"]
    sentiment = raw["sentiment"]
    calendar = raw["calendar"]
    cache = raw["cache"]
    output = raw["output"]

    return NewsConfig(
        rss=RssConfig(
            feeds=list(rss["feeds"]),
            fetch_limit_per_feed=int(rss["fetch_limit_per_feed"]),
        ),
        newsdata=NewsDataConfig(
            enabled=bool(newsdata["enabled"]),
            source_weight=float(newsdata["source_weight"]),
        ),
        sentiment=SentimentConfig(
            llm_model=sentiment["llm_model"],
            llm_batch_size=int(sentiment["llm_batch_size"]),
            llm_source_weight=float(sentiment["llm_source_weight"]),
        ),
        calendar=CalendarConfig(
            crypto_events_enabled=bool(calendar["crypto_events_enabled"]),
            lookahead_days=int(calendar["lookahead_days"]),
            macro_events_file=calendar["macro_events_file"],
            soon_threshold_days=int(calendar["soon_threshold_days"]),
        ),
        cache=NewsCacheConfig(
            dir=cache["dir"],
            raw_ttl_hours=int(cache["raw_ttl_hours"]),
        ),
        output=NewsOutputConfig(dir=output["dir"], save_csv=bool(output["save_csv"])),
    )
