from __future__ import annotations

import pandas as pd

from autotrading.config import RiskParameters
from autotrading.engine import risk as risk_calc
from autotrading.engine.portfolio import Portfolio
from autotrading.strategies.base import Signal


def run_backtest(
    symbol_data: dict[str, pd.DataFrame],
    signals: dict[str, pd.Series],
    initial_capital: float,
    risk: RiskParameters,
    leverage: int = 1,
) -> Portfolio:
    """Single unified event loop across all symbols, sharing one portfolio/equity
    curve so max_concurrent_positions is enforced globally, not per symbol.

    Mirrors how decide_trade_action (decision/engine.py) interprets signals
    live: BUY while flat opens long, SELL while flat opens short, a signal
    opposing the current position closes it, matching signal/HOLD is a
    no-op. `leverage` defaults to 1 (no leverage) so existing callers get
    the exact same behavior as before this was added.

    If a bar's low triggers stop-loss and its high triggers take-profit in
    the same bar, stop-loss wins (conservative assumption) — mirrored for
    shorts. Gaps (a symbol with no candle at a given timestamp) are skipped
    for that symbol at that bar; its last known price is carried forward for
    mark-to-market equity.

    Liquidation is not modeled: with the hardcoded leverage ceiling (10x)
    and a typical stop_loss_pct well under 10%, the stop-loss always fires
    long before a real position would be anywhere near liquidation.
    """
    portfolio = Portfolio(initial_capital)

    all_timestamps: set = set()
    for df in symbol_data.values():
        all_timestamps.update(df.index)
    sorted_timestamps = sorted(all_timestamps)

    last_price: dict[str, float] = {}

    for ts in sorted_timestamps:
        for symbol, df in symbol_data.items():
            if ts not in df.index:
                continue

            bar = df.loc[ts]
            last_price[symbol] = float(bar["close"])
            signal = signals[symbol].loc[ts]

            if symbol in portfolio.open_positions:
                position = portfolio.open_positions[symbol]
                exit_price = None
                exit_reason = None

                if position.side == "long":
                    if bar["low"] <= position.stop_loss:
                        exit_price, exit_reason = position.stop_loss, "stop_loss"
                    elif bar["high"] >= position.take_profit:
                        exit_price, exit_reason = position.take_profit, "take_profit"
                    elif signal == Signal.SELL:
                        exit_price, exit_reason = float(bar["close"]), "signal"
                else:  # short — every trigger direction mirrored
                    if bar["high"] >= position.stop_loss:
                        exit_price, exit_reason = position.stop_loss, "stop_loss"
                    elif bar["low"] <= position.take_profit:
                        exit_price, exit_reason = position.take_profit, "take_profit"
                    elif signal == Signal.BUY:
                        exit_price, exit_reason = float(bar["close"]), "signal"

                if exit_price is not None:
                    fee = risk_calc.exit_fee(exit_price * position.quantity, risk)
                    portfolio.close_position(symbol, ts, exit_price, exit_reason, fee)
            else:
                side = "long" if signal == Signal.BUY else "short" if signal == Signal.SELL else None
                if side is not None and portfolio.can_open_new_position(
                    risk.max_concurrent_positions
                ):
                    entry_price = float(bar["close"])
                    equity = portfolio.equity(last_price)
                    margin = risk_calc.position_notional(equity, risk)
                    quantity = risk_calc.position_quantity(equity, entry_price, risk, leverage)
                    notional = entry_price * quantity
                    fee = risk_calc.entry_fee(notional, risk)
                    if margin + fee <= portfolio.cash:
                        stop_loss = risk_calc.stop_loss_price(entry_price, risk, side, leverage)
                        take_profit = risk_calc.take_profit_price(entry_price, risk, side, leverage)
                        portfolio.open_position(
                            symbol, ts, entry_price, quantity, side, margin,
                            stop_loss, take_profit, fee,
                        )

        portfolio.record_equity(ts, last_price)

    return portfolio
