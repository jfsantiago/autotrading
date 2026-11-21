from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    symbol: str
    entry_time: object
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float


@dataclass
class Trade:
    symbol: str
    entry_time: object
    exit_time: object
    entry_price: float
    exit_price: float
    quantity: float
    exit_reason: str
    pnl: float
    return_pct: float


class Portfolio:
    def __init__(self, initial_capital: float):
        self.cash = initial_capital
        self.open_positions: dict[str, Position] = {}
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[tuple[object, float]] = []

    def equity(self, mark_prices: dict[str, float]) -> float:
        positions_value = sum(
            pos.quantity * mark_prices[symbol]
            for symbol, pos in self.open_positions.items()
            if symbol in mark_prices
        )
        return self.cash + positions_value

    def can_open_new_position(self, max_concurrent_positions: int) -> bool:
        return len(self.open_positions) < max_concurrent_positions

    def open_position(
        self,
        symbol: str,
        entry_time: object,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        fee: float,
    ) -> None:
        notional = entry_price * quantity
        self.cash -= notional + fee
        self.open_positions[symbol] = Position(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def close_position(
        self,
        symbol: str,
        exit_time: object,
        exit_price: float,
        exit_reason: str,
        fee: float,
    ) -> Trade:
        position = self.open_positions.pop(symbol)
        notional = exit_price * position.quantity
        self.cash += notional - fee

        entry_notional = position.entry_price * position.quantity
        pnl = notional - entry_notional - fee
        return_pct = (exit_price - position.entry_price) / position.entry_price

        trade = Trade(
            symbol=symbol,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            exit_reason=exit_reason,
            pnl=pnl,
            return_pct=return_pct,
        )
        self.closed_trades.append(trade)
        return trade

    def record_equity(self, timestamp: object, mark_prices: dict[str, float]) -> None:
        self.equity_curve.append((timestamp, self.equity(mark_prices)))
