from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from autotrading.execution.client import to_futures_symbol


class PositionSide(str, Enum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


@dataclass
class PositionState:
    symbol: str  # canonical spot notation, e.g. "BTC/USDT"
    side: PositionSide
    size: float  # 0.0 if flat
    entry_price: float | None
    margin: float | None = None  # real USDT committed (pre-leverage), from Binance
    unrealized_pnl: float | None = None  # floating PnL if closed right now, from Binance


def get_position_state(
    client: Any, symbol: str, quote_currency: str = "USDT"
) -> PositionState:
    """Query the exchange for the current position on `symbol`, never assumed.

    Binance's futures API is inconsistent about whether a never-opened
    symbol is omitted from fetch_positions entirely or returned with
    contracts=0 — both are treated as FLAT.
    """
    futures_symbol = to_futures_symbol(symbol, quote_currency)
    positions = client.fetch_positions([futures_symbol])

    for position in positions:
        contracts = position.get("contracts") or 0
        if contracts == 0:
            continue
        side_str = position.get("side")
        side = PositionSide.LONG if side_str == "long" else PositionSide.SHORT
        return PositionState(
            symbol=symbol,
            side=side,
            size=abs(contracts),
            entry_price=position.get("entryPrice"),
            margin=position.get("initialMargin"),
            unrealized_pnl=position.get("unrealizedPnl"),
        )

    return PositionState(symbol=symbol, side=PositionSide.FLAT, size=0.0, entry_price=None)
