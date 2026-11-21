import pandas as pd

from autotrading.config import RiskParameters
from autotrading.engine.backtester import run_backtest
from autotrading.strategies.base import Signal


def make_df(bars: list[dict]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(bars), freq="h", tz="UTC")
    return pd.DataFrame(bars, index=index)


def make_signals(values: list[Signal], index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index, dtype=object)


def make_risk(**overrides) -> RiskParameters:
    defaults = dict(
        position_size_pct=0.10,
        stop_loss_pct=0.05,
        take_profit_pct=0.20,
        max_concurrent_positions=5,
        fee_pct=0.0,
    )
    defaults.update(overrides)
    return RiskParameters(**defaults)


def test_signal_exit_closes_at_close_price():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 98, "high": 99, "low": 96, "close": 98, "volume": 1},
            {"open": 108, "high": 111, "low": 105, "close": 110, "volume": 1},
        ]
    )
    signals = make_signals([Signal.BUY, Signal.HOLD, Signal.SELL], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.entry_price == 100.0
    assert trade.exit_price == 110.0
    assert trade.exit_reason == "signal"
    assert trade.quantity == 1.0  # 10% of 1000 equity / 100 entry price
    assert trade.pnl == 10.0
    assert portfolio.cash == 1010.0


def test_stop_loss_exit_uses_stop_price_not_close():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 97, "high": 101, "low": 90, "close": 98, "volume": 1},
        ]
    )
    signals = make_signals([Signal.BUY, Signal.HOLD], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.exit_price == 95.0  # entry 100 * (1 - 0.05)
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl == -5.0


def test_take_profit_exit_uses_take_profit_price():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 115, "high": 125, "low": 99, "close": 115, "volume": 1},
        ]
    )
    signals = make_signals([Signal.BUY, Signal.HOLD], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.exit_price == 120.0  # entry 100 * (1 + 0.20)
    assert trade.exit_reason == "take_profit"


def test_max_concurrent_positions_enforced_across_symbols():
    df_a = make_df([{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}])
    df_b = make_df([{"open": 50, "high": 51, "low": 49, "close": 50, "volume": 1}])

    symbol_data = {"A/USDT": df_a, "B/USDT": df_b}
    signals = {
        "A/USDT": make_signals([Signal.BUY], df_a.index),
        "B/USDT": make_signals([Signal.BUY], df_b.index),
    }

    portfolio = run_backtest(
        symbol_data, signals, initial_capital=1000.0, risk=make_risk(max_concurrent_positions=1)
    )

    assert len(portfolio.open_positions) == 1
    assert "A/USDT" in portfolio.open_positions
    assert "B/USDT" not in portfolio.open_positions
