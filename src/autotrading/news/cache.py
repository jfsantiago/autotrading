from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from autotrading.news.models import LLMClassification, SentimentLabel

logger = logging.getLogger(__name__)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def get_cached_raw(
    cache_dir: Path,
    key: str,
    ttl_hours: float,
    fetch_fn: Callable[[], Any],
) -> Any:
    """Generic short-TTL JSON cache for raw source fetches (RSS/NewsData/CoinMarketCal),
    so repeated `news` runs within the TTL window don't hit external APIs again.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"raw_{_hash_key(key)}.json"

    if path.exists():
        payload = json.loads(path.read_text())
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < timedelta(hours=ttl_hours):
            logger.info("raw cache hit for %s", key)
            return payload["data"]

    logger.info("raw cache miss for %s, fetching", key)
    data = fetch_fn()
    path.write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data})
    )
    return data


def _classification_path(cache_dir: Path, item_id: str) -> Path:
    return cache_dir / "llm" / f"{_hash_key(item_id)}.json"


def get_cached_classification(cache_dir: Path, item_id: str) -> LLMClassification | None:
    path = _classification_path(cache_dir, item_id)
    if not path.exists():
        return None

    payload = json.loads(path.read_text())
    return LLMClassification(
        label=SentimentLabel(payload["label"]),
        confidence=payload["confidence"],
        relevant_symbols=payload["relevant_symbols"],
    )


def save_classification(
    cache_dir: Path, item_id: str, classification: LLMClassification
) -> None:
    path = _classification_path(cache_dir, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "label": classification.label.value,
                "confidence": classification.confidence,
                "relevant_symbols": classification.relevant_symbols,
            }
        )
    )
