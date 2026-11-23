from __future__ import annotations

from typing import Any

import pandas as pd

from autotrading.indicators import rsi, sma
from autotrading.strategies.base import Signal, Strategy


class StableTrendStrategy(Strategy):
    """Moving-average crossover with an RSI filter, for major/stable symbols.

    BUY when the fast MA crosses above the slow MA and RSI is not already
    overbought (<= rsi_buy_max).
    SELL when the fast MA crosses below the slow MA and RSI is not already
    oversold (>= rsi_sell_min) — the exact mirror of BUY's filter.

    SELL is symmetric with BUY on purpose: since decide_trade_action (live)
    and run_backtest both open a SHORT on SELL-while-flat, SELL needs to be
    just as strong a signal as BUY, not merely "this long is a bit
    expensive, I may exit." An earlier version treated `rsi <= rsi_sell_min`
    as an independent, looser SELL trigger (a plain overbought-style exit)
    — which, once SELL could also open a short, meant the bot shorted on a
    condition that's really a contrarian-bounce zone, not a confirmed
    downtrend. Confirmed via backtest: that asymmetry made the short side
    fire ~6x more often than the long side and accounted for the majority
    of the (very real) losses.
    """

    def generate_signals(self, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
        fast = sma(df["close"], params["fast_ma"])
        slow = sma(df["close"], params["slow_ma"])
        rsi_series = rsi(df["close"], params["rsi_period"])

        fast_above_slow = fast > slow
        # bool.shift() upcasts to object dtype (NaN in row 0), so fillna's
        # result must be cast back to bool before negating with `~` —
        # otherwise `~` does Python's bitwise invert on object dtype
        # (~True == -2) instead of logical negation.
        prev_fast_above_slow = fast_above_slow.shift(1).fillna(False).astype(bool)
        crossed_up = fast_above_slow & ~prev_fast_above_slow
        crossed_down = ~fast_above_slow & prev_fast_above_slow

        buy = crossed_up & (rsi_series <= params["rsi_buy_max"])
        sell = crossed_down & (rsi_series >= params["rsi_sell_min"])

        signals = pd.Series(Signal.HOLD, index=df.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[sell & ~buy] = Signal.SELL

        valid = fast.notna() & slow.notna() & rsi_series.notna()
        signals[~valid] = Signal.HOLD

        return signals
