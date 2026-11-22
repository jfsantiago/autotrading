from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import psycopg2
from psycopg2.extras import execute_values

from autotrading.news.models import LLMClassification, SentimentLabel
from autotrading.secrets import Secrets

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


def get_cached_classifications(
    secrets: Secrets, item_ids: list[str]
) -> dict[str, LLMClassification]:
    """Permanent classification cache, backed by Supabase Postgres so it's
    shared between the scheduled VPS runs and any local/manual run (and
    survives a server rebuild), rather than being private to one machine's
    disk. One bulk query per call, not one connection per headline.
    """
    if not item_ids:
        return {}

    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, label, confidence, relevant_symbols "
            "FROM llm_classification_cache WHERE item_id = ANY(%s)",
            (item_ids,),
        )
        rows = cur.fetchall()

    return {
        item_id: LLMClassification(
            label=SentimentLabel(label),
            confidence=confidence,
            relevant_symbols=list(symbols),
        )
        for item_id, label, confidence, symbols in rows
    }


def save_classifications(
    secrets: Secrets, classifications: dict[str, LLMClassification]
) -> None:
    if not classifications:
        return

    rows = [
        (item_id, c.label.value, c.confidence, json.dumps(c.relevant_symbols))
        for item_id, c in classifications.items()
    ]
    with psycopg2.connect(secrets.supabase_db_url) as conn, conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO llm_classification_cache "
            "(item_id, label, confidence, relevant_symbols) VALUES %s "
            "ON CONFLICT (item_id) DO UPDATE SET "
            "label = EXCLUDED.label, confidence = EXCLUDED.confidence, "
            "relevant_symbols = EXCLUDED.relevant_symbols",
            rows,
            template="(%s, %s, %s, %s::jsonb)",
        )
        conn.commit()
