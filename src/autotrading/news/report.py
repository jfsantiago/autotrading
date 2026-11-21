from __future__ import annotations

from pathlib import Path

import pandas as pd

from autotrading.news.models import ScoredItem, SymbolSentiment, UpcomingEvent


def print_news_summary(
    symbol_sentiments: dict[str, SymbolSentiment], upcoming_events: list[UpcomingEvent]
) -> None:
    print("=== News & sentiment snapshot ===")
    if not symbol_sentiments:
        print("No scored news items matched any configured symbol.")
    for symbol, sentiment in symbol_sentiments.items():
        print(
            f"{symbol}: avg_score={sentiment.average_score:+.2f} "
            f"items={sentiment.item_count}"
        )

    print()
    print("--- Upcoming events ---")
    if not upcoming_events:
        print("No upcoming events found.")
    for event in upcoming_events:
        marker = "SOON" if event.is_soon else ""
        symbol = f" [{event.symbol}]" if event.symbol else ""
        print(f"{event.date} ({event.category}){symbol} {event.label} {marker}")


def save_news_results(
    scored_items: list[ScoredItem],
    symbol_sentiments: dict[str, SymbolSentiment],
    upcoming_events: list[UpcomingEvent],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    items_df = pd.DataFrame(
        [
            {
                "source": s.item.source,
                "title": s.item.title,
                "link": s.item.link,
                "published_at": s.item.published_at,
                "label": s.label.value,
                "score": s.score,
                "symbols": ",".join(s.symbols),
            }
            for s in scored_items
        ]
    )
    items_df.to_csv(output_dir / "news_items.csv", index=False)

    sentiment_df = pd.DataFrame(
        [
            {"symbol": s.symbol, "average_score": s.average_score, "item_count": s.item_count}
            for s in symbol_sentiments.values()
        ]
    )
    sentiment_df.to_csv(output_dir / "symbol_sentiment.csv", index=False)

    events_df = pd.DataFrame(
        [
            {
                "date": e.date,
                "category": e.category,
                "symbol": e.symbol,
                "label": e.label,
                "is_soon": e.is_soon,
            }
            for e in upcoming_events
        ]
    )
    events_df.to_csv(output_dir / "upcoming_events.csv", index=False)
