from __future__ import annotations

from typing import Any

import pandas as pd

from autotrading.indicators import rsi, sma
from autotrading.strategies.base import Signal, Strategy


class StableTrendStrategy(Strategy):
    """Moving-average crossover with an RSI filter, for major/stable symbols.

    BUY when the fast MA crosses above the slow MA and RSI is not already
    overbought (<= rsi_buy_max).
    SELL when the fast MA crosses below the slow MA, or RSI drops to/below
    rsi_sell_min (oversold exit, independent of the MA cross).
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
        sell = crossed_down | (rsi_series <= params["rsi_sell_min"])

        signals = pd.Series(Signal.HOLD, index=df.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[sell & ~buy] = Signal.SELL

        valid = fast.notna() & slow.notna() & rsi_series.notna()
        signals[~valid] = Signal.HOLD

        return signals
