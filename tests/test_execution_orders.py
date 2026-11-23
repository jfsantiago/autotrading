from unittest.mock import MagicMock, call, patch

import pytest

from autotrading.execution.orders import (
    close_position,
    fetch_realized_pnl,
    open_long,
    open_short,
    prepare_symbol_for_trading,
)
from autotrading.execution.positions import PositionSide, PositionState


def make_client(position_after_entry):
    client = MagicMock()
    client.create_order = MagicMock(side_effect=[{"id": "entry-1"}, {"id": "stop-1"}])
    client.fetch_positions = MagicMock(return_value=[position_after_entry])
    client.price_to_precision = MagicMock(side_effect=lambda symbol, price: price)
    client.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: amount)
    return client


def test_open_long_sets_margin_leverage_and_places_stop():
    client = make_client({"contracts": 1.5, "side": "long", "entryPrice": 50000.0})

    result = open_long(client, "BTC/USDT", quantity=1.5, leverage=4, stop_loss_pct=0.03)

    client.set_margin_mode.assert_called_once_with("isolated", "BTC/USDT:USDT")
    client.set_leverage.assert_called_once_with(4, "BTC/USDT:USDT")

    entry_call, stop_call = client.create_order.call_args_list
    assert entry_call.args == ("BTC/USDT:USDT", "market", "buy", 1.5)
    assert stop_call.args[:3] == ("BTC/USDT:USDT", "STOP_MARKET", "sell")
    assert stop_call.args[3] == 1.5
    assert stop_call.args[5]["stopPrice"] == pytest.approx(50000.0 * 0.97)
    assert stop_call.args[5]["reduceOnly"] is True

    assert result.action == "open_long"
    assert result.filled_price == 50000.0


def test_open_long_pepe_divides_quantity_by_1000_for_futures_contract():
    # PEPE's quantity is computed from the real per-token spot price, but
    # Binance's "1000PEPE" futures contract is denominated in batches of
    # 1000 tokens — sending the raw token count overshoots the exchange's
    # max order quantity (-4005, confirmed live).
    client = make_client({"contracts": 5.0, "side": "long", "entryPrice": 0.000007})

    open_long(client, "PEPE/USDT", quantity=5000.0, leverage=4, stop_loss_pct=0.03)

    entry_call, _ = client.create_order.call_args_list
    assert entry_call.args == ("1000PEPE/USDT:USDT", "market", "buy", 5.0)


def test_open_short_places_stop_above_entry():
    client = make_client({"contracts": 2.0, "side": "short", "entryPrice": 3000.0})

    result = open_short(client, "ETH/USDT", quantity=2.0, leverage=5, stop_loss_pct=0.05)

    entry_call, stop_call = client.create_order.call_args_list
    assert entry_call.args == ("ETH/USDT:USDT", "market", "sell", 2.0)
    assert stop_call.args[:3] == ("ETH/USDT:USDT", "STOP_MARKET", "buy")
    assert stop_call.args[5]["stopPrice"] == pytest.approx(3000.0 * 1.05)
    assert result.action == "open_short"


def test_margin_mode_already_set_error_is_swallowed():
    client = make_client({"contracts": 1.0, "side": "long", "entryPrice": 100.0})
    client.set_margin_mode.side_effect = Exception('{"code":-4046,"msg":"No need to change margin type."}')

    # should not raise
    open_long(client, "BTC/USDT", quantity=1.0, leverage=2, stop_loss_pct=0.03)


def test_other_margin_mode_error_propagates():
    client = make_client({"contracts": 1.0, "side": "long", "entryPrice": 100.0})
    client.set_margin_mode.side_effect = Exception("some other failure")

    with pytest.raises(Exception, match="some other failure"):
        open_long(client, "BTC/USDT", quantity=1.0, leverage=2, stop_loss_pct=0.03)


def test_close_position_sends_reduce_only_opposite_side_and_cancels_orders():
    client = MagicMock()
    client.create_order = MagicMock(return_value={"id": "close-1", "average": None})
    client.fetch_order = MagicMock(
        return_value={"id": "close-1", "average": 50100.0, "timestamp": 1_700_000_000_000}
    )
    client.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: amount)
    client.fapiPrivateGetIncome = MagicMock(return_value=[{"income": "12.5"}])

    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.5, entry_price=50000.0)
    result = close_position(client, "BTC/USDT", position)

    client.create_order.assert_called_once_with(
        "BTC/USDT:USDT", "market", "sell", 1.5, None, {"reduceOnly": True}
    )
    client.fetch_order.assert_called_once_with("close-1", "BTC/USDT:USDT")
    assert client.cancel_all_orders.call_args_list == [
        call("BTC/USDT:USDT"),
        call("BTC/USDT:USDT", {"trigger": True}),
    ]
    assert result.action == "close"
    assert result.filled_price == 50100.0
    assert result.realized_pnl == pytest.approx(12.5)


def test_close_short_position_sends_buy_side():
    client = MagicMock()
    client.create_order = MagicMock(return_value={"id": "close-2", "average": None})
    client.fetch_order = MagicMock(
        return_value={"id": "close-2", "average": 2950.0, "timestamp": 1_700_000_000_000}
    )
    client.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: amount)
    client.fapiPrivateGetIncome = MagicMock(return_value=[])

    position = PositionState(symbol="ETH/USDT", side=PositionSide.SHORT, size=2.0, entry_price=3000.0)
    close_position(client, "ETH/USDT", position)

    client.create_order.assert_called_once_with(
        "ETH/USDT:USDT", "market", "buy", 2.0, None, {"reduceOnly": True}
    )


def test_prepare_symbol_for_trading_rejects_unsafe_leverage():
    client = MagicMock()
    with pytest.raises(ValueError):
        prepare_symbol_for_trading(client, "BTC/USDT:USDT", leverage=50)
    client.set_margin_mode.assert_not_called()


def test_fetch_realized_pnl_sums_multiple_entries():
    client = MagicMock()
    client.market_id = MagicMock(return_value="BTCUSDT")
    client.fapiPrivateGetIncome = MagicMock(
        return_value=[{"income": "12.5"}, {"income": "-0.3"}]
    )

    result = fetch_realized_pnl(client, "BTC/USDT:USDT", since_ms=1_700_000_000_000)

    assert result == pytest.approx(12.2)
    client.market_id.assert_called_once_with("BTC/USDT:USDT")
    client.fapiPrivateGetIncome.assert_called_once_with(
        {
            "symbol": "BTCUSDT",
            "incomeType": "REALIZED_PNL",
            "startTime": 1_700_000_000_000,
            "limit": 20,
        }
    )


def test_fetch_realized_pnl_retries_once_then_returns_none(monkeypatch):
    monkeypatch.setattr("autotrading.execution.orders.time.sleep", lambda _: None)
    client = MagicMock()
    client.fapiPrivateGetIncome = MagicMock(return_value=[])

    result = fetch_realized_pnl(client, "BTC/USDT:USDT", since_ms=1_700_000_000_000)

    assert result is None
    assert client.fapiPrivateGetIncome.call_count == 2


def test_fetch_realized_pnl_returns_none_on_exception():
    client = MagicMock()
    client.fapiPrivateGetIncome = MagicMock(side_effect=Exception("boom"))

    result = fetch_realized_pnl(client, "BTC/USDT:USDT", since_ms=1_700_000_000_000)

    assert result is None
