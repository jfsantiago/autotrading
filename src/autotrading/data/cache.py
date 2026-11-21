from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)


def _cache_path(cache_dir: Path, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> Path:
    safe_symbol = symbol.replace("/", "-")
    filename = f"{safe_symbol}_{timeframe}_{since_ms}_{until_ms}.csv"
    return cache_dir / filename


def get_cached_ohlcv(
    cache_dir: Path,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    fetch_fn: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    """Return cached OHLCV for the exact (symbol, timeframe, since, until) key,
    fetching and caching via fetch_fn on a miss.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, symbol, timeframe, since_ms, until_ms)

    if path.exists():
        logger.info("cache hit for %s %s", symbol, timeframe)
        df = pd.read_csv(path, parse_dates=["datetime"], index_col="datetime")
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    logger.info("cache miss for %s %s, fetching from exchange", symbol, timeframe)
    df = fetch_fn()
    df.to_csv(path)
    return df
