from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

from autotrading.news.cache import get_cached_raw
from autotrading.news.models import NewsItem, SentimentLabel
from autotrading.secrets import Secrets

logger = logging.getLogger(__name__)

NEWSDATA_URL = "https://newsdata.io/api/1/crypto"
MAX_COINS_PER_QUERY = 5

_NATIVE_LABEL_MAP = {
    "positive": SentimentLabel.BULLISH,
    "negative": SentimentLabel.BEARISH,
    "neutral": SentimentLabel.NEUTRAL,
}


def _base_symbols(symbols: list[str]) -> list[str]:
    """'BTC/USDT' -> 'BTC', deduplicated, capped at NewsData's per-query coin limit."""
    seen: list[str] = []
    for symbol in symbols:
        base = symbol.split("/")[0]
        if base not in seen:
            seen.append(base)
    return seen[:MAX_COINS_PER_QUERY]


def _parse_published(raw_date: str | None) -> datetime:
    if not raw_date:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def fetch_newsdata_items(
    secrets: Secrets, symbols: list[str], cache_dir: Path, ttl_hours: float
) -> list[NewsItem]:
    if not secrets.newsdata_api_key:
        logger.warning("NEWSDATA_API_KEY not set, skipping NewsData.io source")
        return []

    coins = _base_symbols(symbols)
    if not coins:
        return []

    cache_key = f"newsdata:{','.join(coins)}"

    def _fetch() -> dict:
        response = requests.get(
            NEWSDATA_URL,
            params={"apikey": secrets.newsdata_api_key, "coin": ",".join(coins)},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = get_cached_raw(cache_dir, cache_key, ttl_hours, _fetch)
    except Exception:
        logger.exception("NewsData.io fetch failed, degrading to no items")
        return []

    items: list[NewsItem] = []
    for result in payload.get("results", []):
        link = result.get("link")
        title = result.get("title")
        if not link or not title:
            continue

        native_label = _NATIVE_LABEL_MAP.get((result.get("sentiment") or "").lower())
        native_symbols = [c.upper() for c in (result.get("coin") or []) if isinstance(c, str)]

        items.append(
            NewsItem(
                item_id=f"newsdata:{link}",
                source="newsdata.io",
                title=title,
                link=link,
                published_at=_parse_published(result.get("pubDate")),
                native_label=native_label,
                native_symbols=native_symbols or coins,
            )
        )
    return items
