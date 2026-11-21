from __future__ import annotations

import hashlib
import logging
from calendar import timegm
from datetime import datetime, timezone

import feedparser

from autotrading.news.models import NewsItem

logger = logging.getLogger(__name__)


def _item_id(source: str, link: str) -> str:
    return hashlib.sha256(f"{source}:{link}".encode("utf-8")).hexdigest()[:24]


def _parse_published(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        return datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


def fetch_one_feed(feed_url: str, limit: int) -> list[NewsItem]:
    parsed = feedparser.parse(feed_url)
    if parsed.get("bozo"):
        logger.warning("feed parse issue for %s: %s", feed_url, parsed.get("bozo_exception"))

    source = parsed.feed.get("title", feed_url) if parsed.get("feed") else feed_url

    items = []
    for entry in parsed.entries[:limit]:
        link = entry.get("link", "")
        title = entry.get("title", "")
        if not link or not title:
            continue
        items.append(
            NewsItem(
                item_id=_item_id(source, link),
                source=source,
                title=title,
                link=link,
                published_at=_parse_published(entry),
            )
        )
    return items


def fetch_rss_items(feed_urls: list[str], limit_per_feed: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for feed_url in feed_urls:
        try:
            items.extend(fetch_one_feed(feed_url, limit_per_feed))
        except Exception:
            logger.exception("failed to fetch feed %s", feed_url)
    return items
