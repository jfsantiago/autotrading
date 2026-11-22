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


def test_to_futures_symbol_applies_1000x_override():
    # Binance has no "PEPE/USDT:USDT" futures market, only "1000PEPE/USDT:USDT"
    # - confirmed live against the real exchange.
    assert to_futures_symbol("PEPE/USDT") == "1000PEPE/USDT:USDT"


def test_to_futures_symbol_leaves_unaffected_symbols_alone():
    assert to_futures_symbol("WIF/USDT") == "WIF/USDT:USDT"
    assert to_futures_symbol("INJ/USDT") == "INJ/USDT:USDT"


@pytest.mark.parametrize("leverage", [1, 4, MAX_LEVERAGE_CEILING])
def test_assert_leverage_safe_accepts_in_range(leverage):
    assert_leverage_safe(leverage)  # should not raise


@pytest.mark.parametrize("leverage", [0, -1, MAX_LEVERAGE_CEILING + 1, 100])
def test_assert_leverage_safe_rejects_out_of_range(leverage):
    with pytest.raises(ValueError):
        assert_leverage_safe(leverage)
