from __future__ import annotations

from typing import Any

import pandas as pd

from autotrading.indicators import pct_change_over, volume_zscore
from autotrading.strategies.base import Signal, Strategy


class VolatileBreakoutStrategy(Strategy):
    """Momentum breakout with a volume-spike confirmation, for volatile/low-cap symbols.

    BUY when price has risen by at least pct_change_threshold over
    pct_change_window bars AND volume is spiking (z-score >= volume_spike_zscore).
    SELL when price has FALLEN by at least pct_change_threshold over the
    same window AND volume is spiking too — the exact mirror of BUY.

    SELL used to be just `pct_change <= 0` ("momentum isn't positive
    anymore"), with no volume requirement — reasonable as a loose long-exit
    heuristic, but since decide_trade_action (live) and run_backtest both
    open a SHORT on SELL-while-flat, that loose condition was firing far
    more often than BUY's much stricter one. Confirmed via backtest: the
    short side ended up with ~6x the trade count of the long side and the
    bulk of total losses, simply because "not currently pumping" is true
    most of the time and was never a real bearish-breakout confirmation.
    """

    def generate_signals(self, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
        pct_change = pct_change_over(df["close"], params["pct_change_window"])
        vol_z = volume_zscore(df["volume"], params["volume_window"])

        buy = (pct_change >= params["pct_change_threshold"]) & (
            vol_z >= params["volume_spike_zscore"]
        )
        sell = (pct_change <= -params["pct_change_threshold"]) & (
            vol_z >= params["volume_spike_zscore"]
        )

        signals = pd.Series(Signal.HOLD, index=df.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[sell & ~buy] = Signal.SELL

        valid = pct_change.notna() & vol_z.notna()
        signals[~valid] = Signal.HOLD

        return signals
