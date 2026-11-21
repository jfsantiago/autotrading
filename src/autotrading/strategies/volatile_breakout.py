from __future__ import annotations

from typing import Any

import pandas as pd

from autotrading.indicators import pct_change_over, volume_zscore
from autotrading.strategies.base import Signal, Strategy


class VolatileBreakoutStrategy(Strategy):
    """Momentum breakout with a volume-spike confirmation, for volatile/low-cap symbols.

    BUY when price has risen by at least pct_change_threshold over
    pct_change_window bars AND volume is spiking (z-score >= volume_spike_zscore).
    SELL when the momentum that triggered entry fades (pct change over the
    same window turns non-positive) — treated as the exit signal regardless
    of the volume condition.
    """

    def generate_signals(self, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
        pct_change = pct_change_over(df["close"], params["pct_change_window"])
        vol_z = volume_zscore(df["volume"], params["volume_window"])

        buy = (pct_change >= params["pct_change_threshold"]) & (
            vol_z >= params["volume_spike_zscore"]
        )
        sell = pct_change <= 0

        signals = pd.Series(Signal.HOLD, index=df.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[sell & ~buy] = Signal.SELL

        valid = pct_change.notna() & vol_z.notna()
        signals[~valid] = Signal.HOLD

        return signals
