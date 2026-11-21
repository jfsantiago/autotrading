from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autotrading.news import cache as news_cache
from autotrading.news.models import LLMClassification, NewsItem, SentimentLabel

logger = logging.getLogger(__name__)

CLASSIFY_TOOL = {
    "name": "submit_classifications",
    "description": "Classify each crypto news headline's likely short-term price impact.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The headline's id, copied as given"},
                        "label": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "relevant_symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Which of the provided symbols this headline is actually about, if any",
                        },
                    },
                    "required": ["id", "label", "confidence", "relevant_symbols"],
                },
            }
        },
        "required": ["classifications"],
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
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_classifications":
            results = {}
            for entry in block.input.get("classifications", []):
                try:
                    results[entry["id"]] = LLMClassification(
                        label=SentimentLabel(entry["label"]),
                        confidence=float(entry["confidence"]),
                        relevant_symbols=list(entry.get("relevant_symbols", [])),
                    )
                except (KeyError, ValueError):
                    logger.warning("malformed classification entry: %r", entry)
            return results
    logger.warning("no tool_use block found in LLM response")
    return {}


def classify_headlines_batch(
    client: Any,
    items: list[NewsItem],
    universe_symbols: list[str],
    cache_dir: Path,
    model: str,
    batch_size: int,
) -> dict[str, LLMClassification]:
    """Classify items needing LLM sentiment (those without a native_label),
    using a permanent per-item cache and batched tool-use calls so each
    headline is only ever classified once.
    """
    results: dict[str, LLMClassification] = {}
    to_classify: list[NewsItem] = []

    for item in items:
        cached = news_cache.get_cached_classification(cache_dir, item.item_id)
        if cached is not None:
            results[item.item_id] = cached
        else:
            to_classify.append(item)

    for i in range(0, len(to_classify), batch_size):
        batch = to_classify[i : i + batch_size]
        prompt = _build_prompt(batch, universe_symbols)

        response = client.messages.create(
            model=model,
            max_tokens=2048,
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "submit_classifications"},
            messages=[{"role": "user", "content": prompt}],
        )
        batch_results = _parse_response(response)

        for item in batch:
            classification = batch_results.get(item.item_id)
            if classification is None:
                logger.warning("LLM omitted id %s, falling back to neutral", item.item_id)
                classification = LLMClassification(
                    label=SentimentLabel.NEUTRAL, confidence=0.0, relevant_symbols=[]
                )
            news_cache.save_classification(cache_dir, item.item_id, classification)
            results[item.item_id] = classification

    return results
