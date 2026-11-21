from __future__ import annotations

from pathlib import Path

import pandas as pd

from autotrading.decision.engine import OrderAction, TradeDecision
from autotrading.execution.orders import OrderResult
from autotrading.news.models import SymbolSentiment

PREVIEW_BANNER = (
    "=" * 60
    + "\nTRADE PREVIEW (testnet) — position-aware. No orders sent yet.\n"
    + "Run again with --confirm to place these orders on the Binance\n"
    + "Futures TESTNET (fake money, not a real account).\n"
    + "=" * 60
)

EXECUTED_BANNER_TOP = "#" * 60
EXECUTED_BANNER_BOTTOM = "#" * 60


def _news_display(symbol: str, symbol_sentiments: dict[str, SymbolSentiment]) -> str:
    sentiment = symbol_sentiments.get(symbol)
    if sentiment is None:
        return "no coverage"
    return f"{sentiment.average_score:+.2f} ({sentiment.item_count})"


def print_trade_preview(
    decisions: list[TradeDecision], symbol_sentiments: dict[str, SymbolSentiment]
) -> None:
    print(PREVIEW_BANNER)
    for decision in decisions:
        news_display = _news_display(decision.symbol, symbol_sentiments)
        print(
            f"{decision.symbol:<10}: technical={decision.technical_signal.value:<5} "
            f"position={decision.position_side.value:<5} news={news_display:<16} "
            f"-> {decision.order_action.value.upper()} ({decision.reason})"
        )


def print_order_executed(decision: TradeDecision, result: OrderResult) -> None:
    print(EXECUTED_BANNER_TOP)
    print(f"TESTNET ORDER EXECUTED (fake money) — {decision.symbol}: {result.action.upper()}")
    print(f"  entry order id: {result.entry_order.get('id')}   filled qty: {result.filled_quantity}")
    if result.filled_price is not None:
        print(f"  avg price: {result.filled_price}")
    if result.stop_order is not None:
        print(f"  stop order id: {result.stop_order.get('id')}")
    elif result.action == "close":
        print("  stop order cancelled (position closed)")
    print(EXECUTED_BANNER_BOTTOM)


def print_no_action(decision: TradeDecision) -> None:
    print(f"NO ACTION — {decision.symbol}: {decision.reason}")


def print_confirm_footer() -> None:
    print("\nThese were Binance Futures TESTNET orders (fake money), not real trades.")


def save_trade_results(
    decisions: list[TradeDecision],
    executed_results: dict[str, OrderResult],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for decision in decisions:
        result = executed_results.get(decision.symbol)
        rows.append(
            {
                "symbol": decision.symbol,
                "technical_signal": decision.technical_signal.value,
                "position_side": decision.position_side.value,
                "news_score": decision.news_score,
                "order_action": decision.order_action.value,
                "reason": decision.reason,
                "order_id": result.entry_order.get("id") if result else None,
                "filled_price": result.filled_price if result else None,
            }
        )

    pd.DataFrame(rows).to_csv(output_dir / "trades.csv", index=False)
