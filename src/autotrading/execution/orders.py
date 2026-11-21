from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autotrading.config import RiskParameters
from autotrading.execution.client import assert_leverage_safe, to_futures_symbol
from autotrading.execution.positions import PositionSide, PositionState, get_position_state

MARGIN_MODE = "isolated"  # hardcoded safety invariant, not a config value
NO_MARGIN_CHANGE_NEEDED_CODE = "-4046"


@dataclass
class OrderResult:
    symbol: str
    action: str  # 'open_long' | 'open_short' | 'close'
    entry_order: dict[str, Any]
    stop_order: dict[str, Any] | None
    filled_quantity: float
    filled_price: float | None


def calculate_position_size(
    equity: float, entry_price: float, leverage: int, risk: RiskParameters
) -> float:
    """position_size_pct of equity is the MARGIN at risk; leverage multiplies
    that into the controlled notional — this is what makes leverage amplify
    exposure for the same capital at risk, not just free up margin.
    """
    margin = equity * risk.position_size_pct
    notional = margin * leverage
    return notional / entry_price


def prepare_symbol_for_trading(
    client: Any, futures_symbol: str, leverage: int
) -> None:
    assert_leverage_safe(leverage)
    try:
        client.set_margin_mode(MARGIN_MODE, futures_symbol)
    except Exception as exc:
        if NO_MARGIN_CHANGE_NEEDED_CODE not in str(exc):
            raise
    client.set_leverage(leverage, futures_symbol)


def open_long(
    client: Any,
    symbol: str,
    quantity: float,
    leverage: int,
    stop_loss_pct: float,
    quote_currency: str = "USDT",
) -> OrderResult:
    futures_symbol = to_futures_symbol(symbol, quote_currency)
    prepare_symbol_for_trading(client, futures_symbol, leverage)

    entry_order = client.create_order(futures_symbol, "market", "buy", quantity)

    position = get_position_state(client, symbol, quote_currency)
    stop_price = client.price_to_precision(
        futures_symbol, position.entry_price * (1 - stop_loss_pct)
    )
    stop_qty = client.amount_to_precision(futures_symbol, position.size)
    stop_order = client.create_order(
        futures_symbol, "STOP_MARKET", "sell", stop_qty, None,
        {"stopPrice": stop_price, "reduceOnly": True},
    )

    return OrderResult(
        symbol=symbol,
        action="open_long",
        entry_order=entry_order,
        stop_order=stop_order,
        filled_quantity=position.size,
        filled_price=position.entry_price,
    )


def open_short(
    client: Any,
    symbol: str,
    quantity: float,
    leverage: int,
    stop_loss_pct: float,
    quote_currency: str = "USDT",
) -> OrderResult:
    futures_symbol = to_futures_symbol(symbol, quote_currency)
    prepare_symbol_for_trading(client, futures_symbol, leverage)

    entry_order = client.create_order(futures_symbol, "market", "sell", quantity)

    position = get_position_state(client, symbol, quote_currency)
    stop_price = client.price_to_precision(
        futures_symbol, position.entry_price * (1 + stop_loss_pct)
    )
    stop_qty = client.amount_to_precision(futures_symbol, position.size)
    stop_order = client.create_order(
        futures_symbol, "STOP_MARKET", "buy", stop_qty, None,
        {"stopPrice": stop_price, "reduceOnly": True},
    )

    return OrderResult(
        symbol=symbol,
        action="open_short",
        entry_order=entry_order,
        stop_order=stop_order,
        filled_quantity=position.size,
        filled_price=position.entry_price,
    )


def close_position(
    client: Any, symbol: str, position: PositionState, quote_currency: str = "USDT"
) -> OrderResult:
    futures_symbol = to_futures_symbol(symbol, quote_currency)
    close_side = "sell" if position.side == PositionSide.LONG else "buy"
    quantity = client.amount_to_precision(futures_symbol, position.size)

    entry_order = client.create_order(
        futures_symbol, "market", close_side, quantity, None, {"reduceOnly": True}
    )
    # The stop-loss placed when this position opened doesn't auto-cancel on a
    # separate close order — clean it up so it can't misfire on a future
    # unrelated position on the same symbol.
    client.cancel_all_orders(futures_symbol)

    return OrderResult(
        symbol=symbol,
        action="close",
        entry_order=entry_order,
        stop_order=None,
        filled_quantity=position.size,
        filled_price=entry_order.get("average"),
    )
