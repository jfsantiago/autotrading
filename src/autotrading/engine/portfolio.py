from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    symbol: str
    entry_time: object
    entry_price: float
    quantity: float
    side: str  # "long" or "short"
    margin: float  # capital locked from cash, pre-leverage
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
    side: str  # "long" or "short"
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
        """cash (free capital, margin already excluded) + each open
        position's locked margin + its current unrealized PnL — what you'd
        have if everything closed right now at the mark price. Futures-style
        margin accounting, not spot (margin is "yours" and locked, not spent).
        """
        locked_margin = sum(pos.margin for pos in self.open_positions.values())
        unrealized_pnl = sum(
            self._pnl(pos, mark_prices[symbol])
            for symbol, pos in self.open_positions.items()
            if symbol in mark_prices
        )
        return self.cash + locked_margin + unrealized_pnl

    @staticmethod
    def _pnl(position: Position, price: float) -> float:
        direction = 1 if position.side == "long" else -1
        return (price - position.entry_price) * position.quantity * direction

    def can_open_new_position(self, max_concurrent_positions: int) -> bool:
        return len(self.open_positions) < max_concurrent_positions

    def open_position(
        self,
        symbol: str,
        entry_time: object,
        entry_price: float,
        quantity: float,
        side: str,
        margin: float,
        stop_loss: float,
        take_profit: float,
        fee: float,
    ) -> None:
        self.cash -= margin + fee
        self.open_positions[symbol] = Position(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            quantity=quantity,
            side=side,
            margin=margin,
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
        pnl = self._pnl(position, exit_price) - fee
        self.cash += position.margin + pnl
        # Return on the capital actually at risk (margin), not the raw
        # price move — meaningful now that leverage/margin are modeled.
        return_pct = pnl / position.margin

        trade = Trade(
            symbol=symbol,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            side=position.side,
            exit_reason=exit_reason,
            pnl=pnl,
            return_pct=return_pct,
        )
        self.closed_trades.append(trade)
        return trade

    def record_equity(self, timestamp: object, mark_prices: dict[str, float]) -> None:
        self.equity_curve.append((timestamp, self.equity(mark_prices)))
