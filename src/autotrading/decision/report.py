from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from autotrading.decision.engine import Decision
from autotrading.news.models import SymbolSentiment

DRY_RUN_BANNER = (
    "=" * 60
    + "\nDRY RUN — this is a decision preview only. No orders are placed.\n"
    + "=" * 60
)


def _news_display(symbol: str, symbol_sentiments: dict[str, SymbolSentiment]) -> str:
    sentiment = symbol_sentiments.get(symbol)
    if sentiment is None:
        return "no coverage"
    return f"{sentiment.average_score:+.2f} ({sentiment.item_count} items)"


def print_decisions(
    decisions: list[Decision], symbol_sentiments: dict[str, SymbolSentiment]
) -> None:
    print(DRY_RUN_BANNER)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n=== Live decision snapshot ({now_str}) ===")
    for decision in decisions:
        news_display = _news_display(decision.symbol, symbol_sentiments)
        print(
            f"{decision.symbol:<10}: technical={decision.technical_signal.value:<5} "
            f"news={news_display:<20} -> {decision.action.value:<5} ({decision.reason})"
        )

    print("\nReminder: DRY RUN ONLY — no orders were placed.")


def save_decisions(
    decisions: list[Decision],
    symbol_sentiments: dict[str, SymbolSentiment],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for decision in decisions:
        sentiment = symbol_sentiments.get(decision.symbol)
        rows.append(
            {
                "symbol": decision.symbol,
                "technical_signal": decision.technical_signal.value,
                "news_score": sentiment.average_score if sentiment else None,
                "item_count": sentiment.item_count if sentiment else 0,
                "action": decision.action.value,
                "reason": decision.reason,
            }
        )

    pd.DataFrame(rows).to_csv(output_dir / "decisions.csv", index=False)
