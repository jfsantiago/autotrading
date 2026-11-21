from __future__ import annotations

from autotrading.config import RiskParameters


def position_notional(equity: float, risk: RiskParameters) -> float:
    """Dollar amount to allocate to a new position, sized off current equity."""
    return equity * risk.position_size_pct


def position_quantity(equity: float, entry_price: float, risk: RiskParameters) -> float:
    return position_notional(equity, risk) / entry_price


def stop_loss_price(entry_price: float, risk: RiskParameters) -> float:
    return entry_price * (1 - risk.stop_loss_pct)


def take_profit_price(entry_price: float, risk: RiskParameters) -> float:
    return entry_price * (1 + risk.take_profit_pct)


def entry_fee(notional: float, risk: RiskParameters) -> float:
    return notional * risk.fee_pct


def exit_fee(notional: float, risk: RiskParameters) -> float:
    return notional * risk.fee_pct
