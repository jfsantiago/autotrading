import pandas as pd
import pytest

from autotrading.indicators import pct_change_over, rsi, sma, volume_zscore


def test_sma_basic():
    series = pd.Series([1, 2, 3, 4, 5])
    result = sma(series, period=3)
    assert result.iloc[2] == 2.0
    assert result.iloc[3] == 3.0
    assert result.iloc[4] == 4.0
    assert pd.isna(result.iloc[1])


def test_rsi_all_gains_is_100():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    result = rsi(series, period=14)
    assert result.iloc[-1] == 100.0


def test_rsi_all_losses_is_0():
    series = pd.Series([15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    result = rsi(series, period=14)
    assert result.iloc[-1] == 0.0


def test_pct_change_over():
    series = pd.Series([100.0, 101.0, 102.0, 110.0])
    result = pct_change_over(series, window=3)
    assert result.iloc[3] == pytest.approx((110.0 - 100.0) / 100.0)


def test_volume_zscore_flat_volume_is_zero():
    series = pd.Series([10.0] * 25)
    result = volume_zscore(series, window=20)
    assert result.iloc[-1] == 0.0


def test_volume_zscore_spike_is_positive():
    series = pd.Series([10.0] * 20 + [100.0])
    result = volume_zscore(series, window=20)
    assert result.iloc[-1] > 2.0
