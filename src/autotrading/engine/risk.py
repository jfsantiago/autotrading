from __future__ import annotations

from autotrading.config import RiskParameters


def position_notional(equity: float, risk: RiskParameters) -> float:
    """The MARGIN to lock for a new position (capital actually at risk),
    sized off current equity — despite the name, this is pre-leverage.
    `position_quantity` is what applies leverage on top of this to get the
    actual controlled (leveraged) notional. Kept as `position_notional` for
    backward compatibility with existing callers/tests.
    """
    return equity * risk.position_size_pct


def position_quantity(
    equity: float, entry_price: float, risk: RiskParameters, leverage: int = 1
) -> float:
    """Mirrors execution/orders.py::calculate_position_size() — duplicated
    rather than imported, so the backtest engine stays free of any
    execution/exchange-client dependency (same reasoning as MAX_LEVERAGE_CEILING
    already existing separately in config.py and execution/client.py).
    `leverage` defaults to 1 (no leverage) so existing callers/tests that
    don't pass it keep behaving exactly as before.
    """
    margin = position_notional(equity, risk)
    notional = margin * leverage
    return notional / entry_price


def stop_loss_price(entry_price: float, risk: RiskParameters, side: str = "long") -> float:
    if side == "long":
        return entry_price * (1 - risk.stop_loss_pct)
    return entry_price * (1 + risk.stop_loss_pct)


def take_profit_price(entry_price: float, risk: RiskParameters, side: str = "long") -> float:
    if side == "long":
        return entry_price * (1 + risk.take_profit_pct)
    return entry_price * (1 - risk.take_profit_pct)


def entry_fee(notional: float, risk: RiskParameters) -> float:
    return notional * risk.fee_pct


def exit_fee(notional: float, risk: RiskParameters) -> float:
    return notional * risk.fee_pct
