from __future__ import annotations

from dataclasses import dataclass

from autotrading.engine.portfolio import Trade


@dataclass
class Metrics:
    trade_count: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    total_pnl: float


def max_drawdown_pct(equity_curve: list[tuple[object, float]]) -> float:
    if not equity_curve:
        return 0.0

    running_max = equity_curve[0][1]
    worst_drawdown = 0.0
    for _, equity in equity_curve:
        running_max = max(running_max, equity)
        drawdown = (equity - running_max) / running_max
        worst_drawdown = min(worst_drawdown, drawdown)
    return worst_drawdown * 100


def compute_metrics(
    trades: list[Trade],
    equity_curve: list[tuple[object, float]],
    initial_capital: float,
) -> Metrics:
    trade_count = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    win_rate = (wins / trade_count * 100) if trade_count else 0.0
    total_pnl = sum(t.pnl for t in trades)

    final_equity = equity_curve[-1][1] if equity_curve else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital * 100

    return Metrics(
        trade_count=trade_count,
        win_rate=win_rate,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown_pct(equity_curve),
        total_pnl=total_pnl,
    )


def per_symbol_metrics(trades: list[Trade]) -> dict[str, Metrics]:
    by_symbol: dict[str, list[Trade]] = {}
    for trade in trades:
        by_symbol.setdefault(trade.symbol, []).append(trade)

    result = {}
    for symbol, symbol_trades in by_symbol.items():
        wins = sum(1 for t in symbol_trades if t.pnl > 0)
        count = len(symbol_trades)
        result[symbol] = Metrics(
            trade_count=count,
            win_rate=(wins / count * 100) if count else 0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_pnl=sum(t.pnl for t in symbol_trades),
        )
    return result


def per_side_metrics(trades: list[Trade]) -> dict[str, Metrics]:
    """Long vs. short breakdown — without this there's no way to tell
    whether the short side of a strategy is helping or hurting overall
    performance, since compute_metrics/per_symbol_metrics only ever mix
    both sides together.
    """
    by_side: dict[str, list[Trade]] = {}
    for trade in trades:
        by_side.setdefault(trade.side, []).append(trade)

    result = {}
    for side, side_trades in by_side.items():
        wins = sum(1 for t in side_trades if t.pnl > 0)
        count = len(side_trades)
        result[side] = Metrics(
            trade_count=count,
            win_rate=(wins / count * 100) if count else 0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_pnl=sum(t.pnl for t in side_trades),
        )
    return result
