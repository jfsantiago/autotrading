import pytest

from autotrading.config import RiskParameters
from autotrading.engine import risk


def make_risk(**overrides) -> RiskParameters:
    defaults = dict(
        position_size_pct=0.04,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
        max_concurrent_positions=5,
        fee_pct=0.001,
    )
    defaults.update(overrides)
    return RiskParameters(**defaults)


def test_position_notional_and_quantity():
    r = make_risk(position_size_pct=0.10)
    equity = 1000.0
    notional = risk.position_notional(equity, r)
    assert notional == 100.0

    quantity = risk.position_quantity(equity, entry_price=50.0, risk=r)
    assert quantity == 2.0


def test_stop_loss_and_take_profit_prices():
    r = make_risk(stop_loss_pct=0.05, take_profit_pct=0.10)
    entry_price = 100.0
    assert risk.stop_loss_price(entry_price, r) == pytest.approx(95.0)
    assert risk.take_profit_price(entry_price, r) == pytest.approx(110.0)


def test_fees():
    r = make_risk(fee_pct=0.001)
    assert risk.entry_fee(1000.0, r) == 1.0
    assert risk.exit_fee(2000.0, r) == 2.0
