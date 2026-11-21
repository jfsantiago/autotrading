from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from autotrading.data.exchange import fetch_ohlcv_range
from autotrading.strategies import STRATEGY_REGISTRY
from autotrading.strategies.base import Signal
from autotrading.utils.timeutils import timeframe_to_ms

logger = logging.getLogger(__name__)


def get_latest_signal(
    client: Any,
    symbol: str,
    timeframe: str,
    strategy_name: str,
    params: dict[str, Any],
    lookback_candles: int,
    now_ms: int | None = None,
) -> tuple[Signal, pd.DataFrame]:
    """Fetch the last `lookback_candles` candles up to now and return the
    strategy's signal as of the most recently fully-closed candle.

    Not cached on disk — `decide` is an occasional manual command, not a
    polling loop, so an exact-range cache (keyed by since/until, which
    changes every call since "now" changes) would never hit and would just
    pile up unused files.
    """
    step_ms = timeframe_to_ms(timeframe)
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = now_ms - lookback_candles * step_ms

    df = fetch_ohlcv_range(client, symbol, timeframe, since_ms, now_ms)

    # Drop a trailing candle that hasn't closed yet (its open time + one
    # period extends past "now") — its volume/close are still forming.
    if not df.empty and df["timestamp"].iloc[-1] + step_ms > now_ms:
        df = df.iloc[:-1]

    if df.empty:
        logger.warning("no closed candles available for %s, defaulting to HOLD", symbol)
        return Signal.HOLD, df

    strategy = STRATEGY_REGISTRY[strategy_name]()
    signals = strategy.generate_signals(df, params)
    return signals.iloc[-1], df
