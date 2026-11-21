from __future__ import annotations

import logging

import ccxt
import pandas as pd

from autotrading.utils.timeutils import timeframe_to_ms

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
MAX_CANDLES_PER_CALL = 1000


def make_public_client() -> ccxt.binance:
    """Binance client for public market-data endpoints only. No API key/secret —
    this project does not place real orders in this phase.
    """
    return ccxt.binance({"enableRateLimit": True})


def fetch_ohlcv_range(
    client: ccxt.binance,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> pd.DataFrame:
    """Fetch all candles for `symbol` between since_ms and until_ms (inclusive),
    paginating as needed since exchanges cap candles per call.
    """
    step_ms = timeframe_to_ms(timeframe)
    all_rows: list[list[float]] = []
    cursor = since_ms

    while cursor <= until_ms:
        batch = client.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=MAX_CANDLES_PER_CALL)
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1][0]
        next_cursor = last_ts + step_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < MAX_CANDLES_PER_CALL:
            break

    df = pd.DataFrame(all_rows, columns=OHLCV_COLUMNS)
    df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] <= until_ms)]
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("datetime")
