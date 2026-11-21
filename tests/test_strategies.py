import pandas as pd

from autotrading.strategies.base import Signal
from autotrading.strategies.stable_trend import StableTrendStrategy
from autotrading.strategies.volatile_breakout import VolatileBreakoutStrategy


def make_ohlcv(closes, volumes=None):
    n = len(closes)
    volumes = volumes or [100.0] * n
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def test_stable_trend_buy_then_sell_on_crossover():
    # Flat, then a clear uptrend (fast MA crosses above slow MA), then a
    # clear downtrend (fast MA crosses back below slow MA).
    closes = [10.0] * 6 + [11, 12, 13, 14, 15, 16, 17, 18] + [17, 16, 15, 14, 13, 12, 11, 10]
    df = make_ohlcv(closes)

    params = {
        "fast_ma": 3,
        "slow_ma": 6,
        "rsi_period": 3,
        "rsi_buy_max": 100,
        "rsi_sell_min": -1,
    }
    signals = StableTrendStrategy().generate_signals(df, params)

    buy_indices = signals[signals == Signal.BUY].index
    sell_indices = signals[signals == Signal.SELL].index

    assert len(buy_indices) >= 1
    assert len(sell_indices) >= 1
    assert buy_indices[0] < sell_indices[-1]


def test_volatile_breakout_buy_on_momentum_and_volume_spike():
    closes = [10.0] * 20 + [10.2, 10.4, 10.6, 10.8, 11.5]
    volumes = [100.0] * 20 + [100.0, 100.0, 100.0, 100.0, 500.0]
    df = make_ohlcv(closes, volumes)

    params = {
        "pct_change_window": 5,
        "pct_change_threshold": 0.05,
        "volume_window": 20,
        "volume_spike_zscore": 2.0,
    }
    signals = VolatileBreakoutStrategy().generate_signals(df, params)

    assert signals.iloc[-1] == Signal.BUY


def test_volatile_breakout_sell_when_momentum_fades():
    # Price pops mid-window then falls back below where it started 5 bars ago,
    # so pct_change_over(window=5) at the last bar is negative -> SELL.
    closes = [10.0] * 20 + [11.0, 11.5, 11.0, 10.5, 9.5]
    df = make_ohlcv(closes)

    params = {
        "pct_change_window": 5,
        "pct_change_threshold": 0.05,
        "volume_window": 20,
        "volume_spike_zscore": 2.0,
    }
    signals = VolatileBreakoutStrategy().generate_signals(df, params)

    assert signals.iloc[-1] == Signal.SELL
