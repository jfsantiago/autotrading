from autotrading.decision.market import get_latest_signal
from autotrading.strategies.base import Signal
from autotrading.strategies.stable_trend import StableTrendStrategy

TIMEFRAME = "1h"
STEP_MS = 3_600_000
PARAMS = {"fast_ma": 3, "slow_ma": 6, "rsi_period": 3, "rsi_buy_max": 100, "rsi_sell_min": -1}


class FakeClient:
    def __init__(self, candles):
        self._candles = candles

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        return self._candles


def make_candles(closes, start_ms):
    return [
        [start_ms + i * STEP_MS, c, c, c, c, 1.0]
        for i, c in enumerate(closes)
    ]


def test_trims_forming_candle_and_matches_direct_strategy_computation():
    closes = [10.0] * 6 + [11, 12, 13, 14, 15, 16, 17, 18]
    start_ms = 0
    candles = make_candles(closes, start_ms)
    last_open_ms = candles[-1][0]
    now_ms = last_open_ms + 1_000  # still inside that candle's period -> forming

    client = FakeClient(candles)
    signal, df = get_latest_signal(
        client, "BTC/USDT", TIMEFRAME, "stable_trend", PARAMS, lookback_candles=100, now_ms=now_ms
    )

    assert len(df) == len(closes) - 1  # trailing forming candle dropped

    expected_signals = StableTrendStrategy().generate_signals(df, PARAMS)
    assert signal == expected_signals.iloc[-1]


def test_keeps_candle_if_fully_closed():
    closes = [10.0] * 6 + [11, 12, 13, 14, 15, 16, 17, 18]
    start_ms = 0
    candles = make_candles(closes, start_ms)
    last_open_ms = candles[-1][0]
    now_ms = last_open_ms + STEP_MS + 1_000  # fully past that candle's period

    client = FakeClient(candles)
    _, df = get_latest_signal(
        client, "BTC/USDT", TIMEFRAME, "stable_trend", PARAMS, lookback_candles=100, now_ms=now_ms
    )

    assert len(df) == len(closes)


def test_no_closed_candles_defaults_to_hold():
    candles = make_candles([10.0], 0)
    now_ms = candles[-1][0] + 1_000  # the only candle is still forming

    client = FakeClient(candles)
    signal, df = get_latest_signal(
        client, "BTC/USDT", TIMEFRAME, "stable_trend", PARAMS, lookback_candles=100, now_ms=now_ms
    )

    assert signal == Signal.HOLD
    assert df.empty
