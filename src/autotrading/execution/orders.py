from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from autotrading.config import RiskParameters
from autotrading.execution.client import assert_leverage_safe, to_futures_symbol
from autotrading.execution.positions import PositionSide, PositionState, get_position_state

logger = logging.getLogger(__name__)

MARGIN_MODE = "isolated"  # hardcoded safety invariant, not a config value
NO_MARGIN_CHANGE_NEEDED_CODE = "-4046"
REALIZED_PNL_RETRY_DELAY_SECONDS = 1.5


@dataclass
class OrderResult:
    symbol: str
    action: str  # 'open_long' | 'open_short' | 'close'
    entry_order: dict[str, Any]
    stop_order: dict[str, Any] | None
    filled_quantity: float
    filled_price: float | None
    realized_pnl: float | None = None  # only populated for 'close'


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


def _fetch_realized_pnl(client: Any, futures_symbol: str, since_ms: int) -> float | None:
    """Binance's own booked realized PnL for this close (already nets out
    fees as Binance accounts for them) — more trustworthy than computing
    (exit - entry) * qty ourselves. One immediate query + one short retry:
    Binance books this essentially synchronously for market fills, so a
    full backoff loop would be over-engineering for what should be fast.
    """
    # fapiPrivateGetIncome is a raw/implicit API method — unlike unified
    # methods (create_order, fetch_positions), it does NOT translate the
    # unified symbol to Binance's raw market id itself. Confirmed live:
    # passing "WIF/USDT:USDT" directly raised "Invalid symbol" (-1121);
    # client.market_id() gives the "WIFUSDT" form this endpoint needs.
    raw_symbol = client.market_id(futures_symbol)

    for attempt in range(2):
        try:
            entries = client.fapiPrivateGetIncome(
                {
                    "symbol": raw_symbol,
                    "incomeType": "REALIZED_PNL",
                    "startTime": since_ms,
                    "limit": 20,
                }
            )
        except Exception:
            logger.warning("failed to fetch realized PnL for %s", futures_symbol, exc_info=True)
            return None

        if entries:
            return sum(float(e["income"]) for e in entries)
        if attempt == 0:
            time.sleep(REALIZED_PNL_RETRY_DELAY_SECONDS)

    return None


def close_position(
    client: Any, symbol: str, position: PositionState, quote_currency: str = "USDT"
) -> OrderResult:
    futures_symbol = to_futures_symbol(symbol, quote_currency)
    close_side = "sell" if position.side == PositionSide.LONG else "buy"
    quantity = client.amount_to_precision(futures_symbol, position.size)

    entry_order = client.create_order(
        futures_symbol, "market", close_side, quantity, None, {"reduceOnly": True}
    )
    # A market order's immediate response often lacks the average fill price
    # (seen live: "average": None right after placement) — re-fetch it for
    # the authoritative value, same reasoning as open_long/open_short
    # re-fetching position state instead of trusting the entry response.
    filled_order = client.fetch_order(entry_order.get("id"), futures_symbol)

    # The stop-loss placed when this position opened doesn't auto-cancel on a
    # separate close order — clean it up so it can't misfire on a future
    # unrelated position on the same symbol. STOP_MARKET orders are Binance
    # "algo"/conditional orders, a separate bucket from regular orders —
    # cancelling both is needed to actually remove the stop (confirmed via a
    # live demo-account test: the STOP_MARKET order came back with an
    # 'algoId' in its raw info, and plain cancel_all_orders silently left it
    # in place; passing trigger=True routes to the algo-order endpoint).
    client.cancel_all_orders(futures_symbol)
    client.cancel_all_orders(futures_symbol, {"trigger": True})

    # A PnL-lookup hiccup must never make an already-successful close look
    # like a failure to the caller — realized_pnl simply stays None (honest
    # "unknown" rather than a misleading 0.0 that looks like break-even).
    since_ms = int(filled_order.get("timestamp") or 0) - 5000
    realized_pnl = _fetch_realized_pnl(client, futures_symbol, since_ms)

    return OrderResult(
        symbol=symbol,
        action="close",
        entry_order=entry_order,
        stop_order=None,
        filled_quantity=position.size,
        filled_price=filled_order.get("average"),
        realized_pnl=realized_pnl,
    )
