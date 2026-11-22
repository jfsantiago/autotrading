from __future__ import annotations

import json
import logging
from typing import Any

from autotrading.news import cache as news_cache
from autotrading.news.models import LLMClassification, NewsItem, SentimentLabel
from autotrading.secrets import Secrets

logger = logging.getLogger(__name__)

CLASSIFICATIONS_JSON_SCHEMA = {
    "name": "classifications",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The headline's id, copied as given"},
                        "label": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                        "confidence": {"type": "number"},
                        "relevant_symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["id", "label", "confidence", "relevant_symbols"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
        "additionalProperties": False,
    },
}


def _build_prompt(batch: list[NewsItem], universe_symbols: list[str]) -> str:
    base_symbols = sorted({s.split("/")[0] for s in universe_symbols})
    lines = [
        "Classify each crypto news headline below for its likely short-term price impact.",
        f"Only use symbols from this list for relevant_symbols (base tickers): {', '.join(base_symbols)}.",
        "If a headline is general market news not about a specific symbol, use an empty list.",
        "",
    ]
    for item in batch:
        lines.append(f"id={item.item_id} | {item.title}")
    return "\n".join(lines)


def _parse_response(response: Any) -> dict[str, LLMClassification]:
    content = response.choices[0].message.content
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("could not parse LLM response as JSON: %r", content)
        return {}

    results = {}
    for entry in payload.get("classifications", []):
        try:
            results[entry["id"]] = LLMClassification(
                label=SentimentLabel(entry["label"]),
                confidence=float(entry["confidence"]),
                relevant_symbols=list(entry.get("relevant_symbols", [])),
            )
        except (KeyError, ValueError):
            logger.warning("malformed classification entry: %r", entry)
    return results


def classify_headlines_batch(
    client: Any,
    items: list[NewsItem],
    universe_symbols: list[str],
    secrets: Secrets,
    model: str,
    batch_size: int,
) -> dict[str, LLMClassification]:
    """Classify items needing LLM sentiment (those without a native_label),
    using a permanent cache (Supabase Postgres, survives across ephemeral
    GitHub Actions runs) and batched structured-output calls so each
    headline is only ever classified once, ever.
    """
    item_ids = [item.item_id for item in items]
    cached = news_cache.get_cached_classifications(secrets, item_ids)

    results: dict[str, LLMClassification] = dict(cached)
    to_classify = [item for item in items if item.item_id not in cached]

    for i in range(0, len(to_classify), batch_size):
        batch = to_classify[i : i + batch_size]
        prompt = _build_prompt(batch, universe_symbols)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": CLASSIFICATIONS_JSON_SCHEMA},
        )
        batch_results = _parse_response(response)

        new_classifications: dict[str, LLMClassification] = {}
        for item in batch:
            classification = batch_results.get(item.item_id)
            if classification is None:
                logger.warning("LLM omitted id %s, falling back to neutral", item.item_id)
                classification = LLMClassification(
                    label=SentimentLabel.NEUTRAL, confidence=0.0, relevant_symbols=[]
                )
            new_classifications[item.item_id] = classification

        news_cache.save_classifications(secrets, new_classifications)
        results.update(new_classifications)

    return results
