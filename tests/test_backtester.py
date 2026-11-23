import pandas as pd
import pytest

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


def test_sell_while_flat_opens_a_short():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 95, "high": 96, "low": 94, "close": 90, "volume": 1},
        ]
    )
    signals = make_signals([Signal.SELL, Signal.BUY], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.side == "short"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 90.0
    assert trade.exit_reason == "signal"
    assert trade.pnl == 10.0  # price fell 10 on a short = profit


def test_short_stop_loss_triggers_on_price_rising():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 103, "high": 106, "low": 102, "close": 104, "volume": 1},
        ]
    )
    signals = make_signals([Signal.SELL, Signal.HOLD], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.exit_price == 105.0  # entry 100 * (1 + 0.05), mirrored for short
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl == -5.0


def test_short_take_profit_triggers_on_price_falling():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 85, "high": 90, "low": 75, "close": 80, "volume": 1},
        ]
    )
    signals = make_signals([Signal.SELL, Signal.HOLD], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.exit_price == 80.0  # entry 100 * (1 - 0.20), mirrored for short
    assert trade.exit_reason == "take_profit"


def test_buy_while_short_closes_it_not_opens_a_long():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 98, "high": 99, "low": 96, "close": 98, "volume": 1},
        ]
    )
    signals = make_signals([Signal.SELL, Signal.BUY], df.index)

    portfolio = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk()
    )

    # BUY closed the short on the second bar; it must not also open a new
    # long in the same pass.
    assert "A/USDT" not in portfolio.open_positions
    assert len(portfolio.closed_trades) == 1


def test_leverage_doubles_quantity_and_pnl_for_the_same_price_move():
    df = make_df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 108, "high": 111, "low": 105, "close": 110, "volume": 1},
        ]
    )
    signals = make_signals([Signal.BUY, Signal.SELL], df.index)

    portfolio_1x = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk(), leverage=1
    )
    portfolio_2x = run_backtest(
        {"A/USDT": df}, {"A/USDT": signals}, initial_capital=1000.0, risk=make_risk(), leverage=2
    )

    trade_1x = portfolio_1x.closed_trades[0]
    trade_2x = portfolio_2x.closed_trades[0]
    assert trade_2x.quantity == pytest.approx(trade_1x.quantity * 2)
    assert trade_2x.pnl == pytest.approx(trade_1x.pnl * 2)


def test_leverage_does_not_change_margin_locked_or_concurrent_capacity():
    # By design (mirrors execution/orders.py::calculate_position_size),
    # position_size_pct fixes the MARGIN at risk regardless of leverage —
    # leverage only amplifies the notional/quantity controlled for that same
    # margin, it never frees up capital for more concurrent positions.
    df_a = make_df([{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}])
    df_b = make_df([{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}])
    symbol_data = {"A/USDT": df_a, "B/USDT": df_b}
    signals = {
        "A/USDT": make_signals([Signal.BUY], df_a.index),
        "B/USDT": make_signals([Signal.BUY], df_b.index),
    }
    # margin per position = 1000*0.6 = 600; two positions need 1200 > 1000
    # cash, regardless of leverage, so only one should fit.
    risk = make_risk(position_size_pct=0.6, max_concurrent_positions=5)

    portfolio = run_backtest(symbol_data, signals, initial_capital=1000.0, risk=risk, leverage=4)

    assert len(portfolio.open_positions) == 1
    assert portfolio.open_positions["A/USDT"].margin == 600.0


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
