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


def test_stable_trend_no_sell_when_already_oversold():
    # A bearish cross that lands deep in oversold territory shouldn't open
    # a short — RSI this low is a contrarian-bounce zone, not confirmation
    # of a real downtrend. rsi_sell_min now acts as a floor (mirrors
    # rsi_buy_max's ceiling on BUY), not a standalone exit trigger.
    closes = [10.0] * 6 + [11, 12, 13, 14, 15, 16] + [15, 14, 13, 12, 11, 10, 9, 8, 7, 6]
    df = make_ohlcv(closes)

    params = {
        "fast_ma": 3,
        "slow_ma": 6,
        "rsi_period": 3,
        "rsi_buy_max": 100,
        "rsi_sell_min": 30,
    }
    signals = StableTrendStrategy().generate_signals(df, params)

    assert signals.iloc[-1] != Signal.SELL


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


def test_volatile_breakout_sell_on_confirmed_breakdown_and_volume_spike():
    # Mirror of the BUY test: a confirmed decline (>= threshold) with a
    # volume spike -> SELL. SELL must be just as strong a signal as BUY
    # since it's also used to open a short, not just exit a long.
    closes = [10.0] * 20 + [9.8, 9.6, 9.4, 9.2, 8.5]
    volumes = [100.0] * 20 + [100.0, 100.0, 100.0, 100.0, 500.0]
    df = make_ohlcv(closes, volumes)

    params = {
        "pct_change_window": 5,
        "pct_change_threshold": 0.05,
        "volume_window": 20,
        "volume_spike_zscore": 2.0,
    }
    signals = VolatileBreakoutStrategy().generate_signals(df, params)

    assert signals.iloc[-1] == Signal.SELL


def test_volatile_breakout_no_sell_without_volume_confirmation():
    # Price fell enough to clear the threshold, but without a volume spike
    # this must NOT fire SELL anymore — otherwise it'd open a short on
    # nothing more than "price isn't pumping," which is true most of the
    # time and isn't a real bearish confirmation.
    closes = [10.0] * 20 + [11.0, 11.5, 11.0, 10.5, 9.5]
    df = make_ohlcv(closes)

    params = {
        "pct_change_window": 5,
        "pct_change_threshold": 0.05,
        "volume_window": 20,
        "volume_spike_zscore": 2.0,
    }
    signals = VolatileBreakoutStrategy().generate_signals(df, params)

    assert signals.iloc[-1] == Signal.HOLD
