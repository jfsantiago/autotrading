from autotrading.engine.portfolio import Trade
from autotrading.reporting.metrics import compute_metrics, max_drawdown_pct, per_symbol_metrics


def make_trade(symbol="BTC/USDT", pnl=0.0):
    return Trade(
        symbol=symbol,
        entry_time=0,
        exit_time=1,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        quantity=1.0,
        exit_reason="signal",
        pnl=pnl,
        return_pct=pnl / 100.0,
    )


def test_max_drawdown_known_curve():
    curve = [(0, 100.0), (1, 120.0), (2, 90.0), (3, 110.0)]
    # Peak 120 -> trough 90 is a 25% drawdown.
    assert max_drawdown_pct(curve) == -25.0


def test_max_drawdown_no_drop_is_zero():
    curve = [(0, 100.0), (1, 110.0), (2, 120.0)]
    assert max_drawdown_pct(curve) == 0.0


def test_compute_metrics_win_rate_and_return():
    trades = [make_trade(pnl=10.0), make_trade(pnl=-5.0), make_trade(pnl=20.0)]
    curve = [(0, 1000.0), (1, 1025.0)]
    metrics = compute_metrics(trades, curve, initial_capital=1000.0)

    assert metrics.trade_count == 3
    assert round(metrics.win_rate, 2) == round(2 / 3 * 100, 2)
    assert metrics.total_return_pct == 2.5
    assert metrics.total_pnl == 25.0


def test_per_symbol_metrics_groups_correctly():
    trades = [
        make_trade(symbol="BTC/USDT", pnl=10.0),
        make_trade(symbol="BTC/USDT", pnl=-10.0),
        make_trade(symbol="ETH/USDT", pnl=5.0),
    ]
    by_symbol = per_symbol_metrics(trades)

    assert by_symbol["BTC/USDT"].trade_count == 2
    assert by_symbol["BTC/USDT"].win_rate == 50.0
    assert by_symbol["ETH/USDT"].trade_count == 1
    assert by_symbol["ETH/USDT"].total_pnl == 5.0
