from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    """Classic Wilder RSI using an exponential (Wilder) moving average of gains/losses."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def pct_change_over(series: pd.Series, window: int) -> pd.Series:
    return series.pct_change(periods=window)


def volume_zscore(volume: pd.Series, window: int) -> pd.Series:
    rolling_mean = volume.rolling(window=window, min_periods=window).mean()
    rolling_std = volume.rolling(window=window, min_periods=window).std(ddof=0)
    z = (volume - rolling_mean) / rolling_std
    # Zero variance (flat volume) means no spike, not an undefined ratio.
    return z.where(rolling_std != 0, 0.0)
