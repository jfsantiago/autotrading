from __future__ import annotations

from pathlib import Path

import pandas as pd

from autotrading.engine.portfolio import Portfolio
from autotrading.reporting.metrics import Metrics, compute_metrics, per_symbol_metrics


def print_summary(
    aggregate: Metrics, by_symbol: dict[str, Metrics], initial_capital: float
) -> None:
    print("=== Backtest summary ===")
    print(f"Initial capital: {initial_capital:.2f}")
    print(f"Trades: {aggregate.trade_count}")
    print(f"Win rate: {aggregate.win_rate:.2f}%")
    print(f"Total return: {aggregate.total_return_pct:.2f}%")
    print(f"Max drawdown: {aggregate.max_drawdown_pct:.2f}%")
    print(f"Total PnL: {aggregate.total_pnl:.2f}")
    print()
    print("--- Per symbol ---")
    for symbol, metrics in by_symbol.items():
        print(
            f"{symbol}: trades={metrics.trade_count} "
            f"win_rate={metrics.win_rate:.2f}% pnl={metrics.total_pnl:.2f}"
        )


def save_results(portfolio: Portfolio, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    trades_df = pd.DataFrame(
        [
            {
                "symbol": t.symbol,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "exit_reason": t.exit_reason,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
            }
            for t in portfolio.closed_trades
        ]
    )
    trades_df.to_csv(output_dir / "trades.csv", index=False)

    equity_df = pd.DataFrame(portfolio.equity_curve, columns=["timestamp", "equity"])
    equity_df.to_csv(output_dir / "equity_curve.csv", index=False)


def report(portfolio: Portfolio, initial_capital: float, output_dir: Path, save_csv: bool) -> None:
    aggregate = compute_metrics(portfolio.closed_trades, portfolio.equity_curve, initial_capital)
    by_symbol = per_symbol_metrics(portfolio.closed_trades)

    print_summary(aggregate, by_symbol, initial_capital)

    if save_csv:
        save_results(portfolio, output_dir)

        summary_df = pd.DataFrame(
            [
                {
                    "scope": "aggregate",
                    "trade_count": aggregate.trade_count,
                    "win_rate": aggregate.win_rate,
                    "total_return_pct": aggregate.total_return_pct,
                    "max_drawdown_pct": aggregate.max_drawdown_pct,
                    "total_pnl": aggregate.total_pnl,
                },
                *[
                    {
                        "scope": symbol,
                        "trade_count": m.trade_count,
                        "win_rate": m.win_rate,
                        "total_return_pct": m.total_return_pct,
                        "max_drawdown_pct": m.max_drawdown_pct,
                        "total_pnl": m.total_pnl,
                    }
                    for symbol, m in by_symbol.items()
                ],
            ]
        )
        summary_df.to_csv(output_dir / "summary.csv", index=False)
