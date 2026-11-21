from __future__ import annotations

from autotrading.news.models import ScoredItem, SymbolSentiment


def aggregate_by_symbol(
    scored_items: list[ScoredItem], all_symbols: list[str]
) -> dict[str, SymbolSentiment]:
    """Weighted average sentiment score per configured symbol, across whichever
    sources mentioned it. Items mentioning symbols outside the configured
    universe are ignored for aggregation (still visible in the raw item list).
    """
    base_to_full = {s.split("/")[0].upper(): s for s in all_symbols}

    weighted_sums: dict[str, float] = {}
    total_weights: dict[str, float] = {}
    counts: dict[str, int] = {}

    for scored in scored_items:
        for mentioned_symbol in scored.symbols:
            full_symbol = base_to_full.get(mentioned_symbol.split("/")[0].upper())
            if full_symbol is None:
                continue
            weighted_sums[full_symbol] = (
                weighted_sums.get(full_symbol, 0.0) + scored.score * scored.source_weight
            )
            total_weights[full_symbol] = (
                total_weights.get(full_symbol, 0.0) + scored.source_weight
            )
            counts[full_symbol] = counts.get(full_symbol, 0) + 1

    result = {}
    for full_symbol, count in counts.items():
        weight = total_weights[full_symbol]
        average = weighted_sums[full_symbol] / weight if weight else 0.0
        result[full_symbol] = SymbolSentiment(
            symbol=full_symbol, average_score=average, item_count=count
        )
    return result
