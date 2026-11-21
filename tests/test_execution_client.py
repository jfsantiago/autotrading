import pytest

from autotrading.execution.client import (
    MAX_LEVERAGE_CEILING,
    assert_leverage_safe,
    to_futures_symbol,
)


def test_to_futures_symbol_happy_path():
    assert to_futures_symbol("BTC/USDT") == "BTC/USDT:USDT"


def test_to_futures_symbol_rejects_wrong_quote():
    with pytest.raises(ValueError):
        to_futures_symbol("BTC/BUSD")


@pytest.mark.parametrize("leverage", [1, 4, MAX_LEVERAGE_CEILING])
def test_assert_leverage_safe_accepts_in_range(leverage):
    assert_leverage_safe(leverage)  # should not raise


@pytest.mark.parametrize("leverage", [0, -1, MAX_LEVERAGE_CEILING + 1, 100])
def test_assert_leverage_safe_rejects_out_of_range(leverage):
    with pytest.raises(ValueError):
        assert_leverage_safe(leverage)
