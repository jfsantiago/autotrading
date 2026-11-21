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
) -> Portfolio:
    """Single unified event loop across all symbols, sharing one portfolio/equity
    curve so max_concurrent_positions is enforced globally, not per symbol.

    Long-only. If a bar's low triggers stop-loss and its high triggers
    take-profit in the same bar, stop-loss wins (conservative assumption).
    Gaps (a symbol with no candle at a given timestamp) are skipped for that
    symbol at that bar; its last known price is carried forward for
    mark-to-market equity.
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
                if bar["low"] <= position.stop_loss:
                    exit_price = position.stop_loss
                    fee = risk_calc.exit_fee(exit_price * position.quantity, risk)
                    portfolio.close_position(symbol, ts, exit_price, "stop_loss", fee)
                elif bar["high"] >= position.take_profit:
                    exit_price = position.take_profit
                    fee = risk_calc.exit_fee(exit_price * position.quantity, risk)
                    portfolio.close_position(symbol, ts, exit_price, "take_profit", fee)
                elif signal == Signal.SELL:
                    exit_price = float(bar["close"])
                    fee = risk_calc.exit_fee(exit_price * position.quantity, risk)
                    portfolio.close_position(symbol, ts, exit_price, "signal", fee)
            else:
                if signal == Signal.BUY and portfolio.can_open_new_position(
                    risk.max_concurrent_positions
                ):
                    entry_price = float(bar["close"])
                    equity = portfolio.equity(last_price)
                    quantity = risk_calc.position_quantity(equity, entry_price, risk)
                    notional = entry_price * quantity
                    fee = risk_calc.entry_fee(notional, risk)
                    if notional + fee <= portfolio.cash:
                        stop_loss = risk_calc.stop_loss_price(entry_price, risk)
                        take_profit = risk_calc.take_profit_price(entry_price, risk)
                        portfolio.open_position(
                            symbol, ts, entry_price, quantity, stop_loss, take_profit, fee
                        )

        portfolio.record_equity(ts, last_price)

    return portfolio
