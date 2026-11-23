import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autotrading.execution.orders import OrderResult
from autotrading.execution.positions import PositionSide, PositionState
from autotrading.position_tracking import TrackedPosition
from autotrading.scheduling import BotState
from autotrading.secrets import Secrets
from autotrading.telegram_bot import (
    _fmt_num,
    _is_authorized,
    cmd_balance,
    cmd_close,
    cmd_history,
    cmd_positions,
    cmd_set_leverage,
    cmd_set_risk,
    cmd_settings,
    cmd_status,
    cmd_universe,
    notify,
    on_close_callback,
    require_telegram_secrets,
)
from autotrading.trade_history import ClosedTrade

AUTHORIZED_CHAT_ID = 111


def make_secrets(chat_id=AUTHORIZED_CHAT_ID, bot_token="tok"):
    return Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
    )


def make_update(chat_id):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def make_context(args=None, **bot_data):
    context = MagicMock()
    context.bot_data = bot_data
    context.args = args if args is not None else []
    return context


def make_callback_update(chat_id, data):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def test_is_authorized():
    assert _is_authorized(123, 123) is True
    assert _is_authorized(123, 456) is False


def test_require_telegram_secrets_raises_when_missing():
    secrets = make_secrets(bot_token=None)
    with pytest.raises(RuntimeError):
        require_telegram_secrets(secrets)


def test_require_telegram_secrets_ok_when_present():
    require_telegram_secrets(make_secrets())  # should not raise


def test_cmd_positions_ignores_unauthorized_chat():
    secrets = make_secrets()
    update = make_update(chat_id=999)  # not the authorized chat
    context = make_context(secrets=secrets, config=MagicMock(), client=MagicMock())

    asyncio.run(cmd_positions(update, context))

    update.message.reply_text.assert_not_called()


def test_cmd_positions_shows_open_positions_with_unrealized_pnl():
    secrets = make_secrets()
    config = SimpleNamespace(
        all_symbols=["BTC/USDT"], futures=SimpleNamespace(quote_currency="USDT")
    )
    client = MagicMock()
    client.fetch_positions = MagicMock(
        return_value=[
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 1.5,
                "side": "long",
                "entryPrice": 50000.0,
                "unrealizedPnl": 25.0,
                "initialMargin": 300.0,
            }
        ]
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.position_tracking.fetch_all_tracked_positions", return_value={}):
        asyncio.run(cmd_positions(update, context))

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert "BTC" in text  # base ticker only, "/USDT" dropped for table width
    assert "300" in text  # Cant. = margen real en USDT, no la cantidad del activo
    assert "25" in text


def test_cmd_positions_shows_opened_date_from_tracking():
    secrets = make_secrets()
    config = SimpleNamespace(
        all_symbols=["BTC/USDT"], futures=SimpleNamespace(quote_currency="USDT")
    )
    client = MagicMock()
    client.fetch_positions = MagicMock(
        return_value=[
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 1.5,
                "side": "long",
                "entryPrice": 50000.0,
                "unrealizedPnl": 25.0,
                "initialMargin": 300.0,
            }
        ]
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)
    tracked = {
        "BTC/USDT": TrackedPosition(
            symbol="BTC/USDT", position_side="long", quantity=1.5, entry_price=50000.0,
            margin=300.0, opened_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
    }

    with patch(
        "autotrading.telegram_bot.position_tracking.fetch_all_tracked_positions",
        return_value=tracked,
    ):
        asyncio.run(cmd_positions(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "260101:1200" in text  # date format "YYMMDD:HHMM" (2-digit year)


def test_cmd_positions_handles_no_open_positions():
    secrets = make_secrets()
    config = SimpleNamespace(
        all_symbols=["BTC/USDT"], futures=SimpleNamespace(quote_currency="USDT")
    )
    client = MagicMock()
    client.fetch_positions = MagicMock(return_value=[])
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    asyncio.run(cmd_positions(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "Sin posiciones" in text


def test_cmd_universe_lists_both_buckets_with_strategy():
    secrets = make_secrets()
    config = SimpleNamespace(
        stable=SimpleNamespace(symbols=["BTC/USDT", "XRP/USDT"], strategy="stable_trend"),
        volatile=SimpleNamespace(symbols=["PEPE/USDT", "ARB/USDT"], strategy="volatile_breakout"),
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config)

    asyncio.run(cmd_universe(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "BTC" in text and "XRP" in text
    assert "PEPE" in text and "ARB" in text
    assert "tendencia" in text and "ruptura" in text


def test_cmd_universe_ignores_unauthorized_chat():
    secrets = make_secrets()
    config = SimpleNamespace(
        stable=SimpleNamespace(symbols=["BTC/USDT"], strategy="stable_trend"),
        volatile=SimpleNamespace(symbols=["PEPE/USDT"], strategy="volatile_breakout"),
    )
    update = make_update(chat_id=999)
    context = make_context(secrets=secrets, config=config)

    asyncio.run(cmd_universe(update, context))

    update.message.reply_text.assert_not_called()


def test_cmd_history_shows_recent_trades():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets)

    trade = ClosedTrade(
        symbol="BTC/USDT",
        position_side="long",
        quantity=1.0,
        entry_price=100.0,
        exit_price=110.0,
        realized_pnl=10.0,
        closed_via="bot",
        margin=200.0,
        closed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    with patch(
        "autotrading.telegram_bot.trade_history.fetch_recent_closed_trades",
        return_value=[trade],
    ):
        asyncio.run(cmd_history(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "BTC" in text  # base ticker only, "/USDT" dropped for table width
    assert "200" in text  # Cant. = margen real en USDT
    assert "10.0" in text or "+10.0000" in text
    assert "260101:1200" in text  # date format "YYMMDD:HHMM" (2-digit year)
    assert "largo" in text  # "long" translated for display
    assert "bot" in text  # closed_via == "bot" shown in the "Vía" column


def test_cmd_history_marks_stop_loss_closes_distinctly():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets)

    trade = ClosedTrade(
        symbol="BTC/USDT",
        position_side="long",
        quantity=1.0,
        entry_price=100.0,
        exit_price=97.0,
        realized_pnl=-3.0,
        closed_via="stop_loss",
        margin=100.0,
        closed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    with patch(
        "autotrading.telegram_bot.trade_history.fetch_recent_closed_trades",
        return_value=[trade],
    ):
        asyncio.run(cmd_history(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "SL" in text


def test_cmd_history_handles_no_trades():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets)

    with patch(
        "autotrading.telegram_bot.trade_history.fetch_recent_closed_trades", return_value=[]
    ):
        asyncio.run(cmd_history(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "Sin cierres" in text


def test_cmd_status_shows_bot_state():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets)

    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=None)
    with patch("autotrading.telegram_bot.fetch_bot_state", return_value=state):
        asyncio.run(cmd_status(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "ENCENDIDO" in text
    assert "60" in text


def make_config(all_symbols=("BTC/USDT",), leverage=4, position_size_pct=0.04):
    return SimpleNamespace(
        all_symbols=list(all_symbols),
        futures=SimpleNamespace(quote_currency="USDT", leverage=leverage),
        risk=SimpleNamespace(position_size_pct=position_size_pct),
    )


def test_cmd_balance_shows_total_free_and_used():
    secrets = make_secrets()
    config = make_config()
    client = MagicMock()
    client.fetch_balance = MagicMock(
        return_value={"USDT": {"total": 1000.0, "free": 700.0, "used": 300.0}}
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    asyncio.run(cmd_balance(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "1000" in text and "700" in text and "300" in text


def test_cmd_close_no_args_lists_open_positions_as_buttons():
    secrets = make_secrets()
    config = make_config()
    client = MagicMock()
    client.fetch_positions = MagicMock(
        return_value=[
            {"symbol": "BTC/USDT:USDT", "contracts": 1.5, "side": "long", "entryPrice": 50000.0}
        ]
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    asyncio.run(cmd_close(update, context))

    update.message.reply_text.assert_called_once()
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "close_pick:BTC/USDT"


def test_cmd_close_no_args_no_open_positions():
    secrets = make_secrets()
    config = make_config()
    client = MagicMock()
    client.fetch_positions = MagicMock(return_value=[])
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    asyncio.run(cmd_close(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "No hay posiciones abiertas" in text


def test_cmd_close_with_symbol_arg_shows_confirmation_directly():
    secrets = make_secrets()
    config = make_config()
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.5, entry_price=50000.0)
    client = MagicMock()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["BTC"], secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=position):
        asyncio.run(cmd_close(update, context))

    text = update.message.reply_text.call_args.args[0]
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert "BTC" in text and "largo" in text
    assert markup.inline_keyboard[0][0].callback_data == "close_confirm:BTC/USDT"


def test_cmd_close_with_symbol_arg_not_open():
    secrets = make_secrets()
    config = make_config()
    flat = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    client = MagicMock()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["BTC"], secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=flat):
        asyncio.run(cmd_close(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "No hay posición abierta" in text


def test_on_close_callback_ignores_unauthorized_chat():
    secrets = make_secrets()
    update = make_callback_update(chat_id=999, data="close_cancel")
    context = make_context(secrets=secrets)

    asyncio.run(on_close_callback(update, context))

    update.callback_query.answer.assert_not_called()


def test_on_close_callback_cancel():
    secrets = make_secrets()
    update = make_callback_update(chat_id=AUTHORIZED_CHAT_ID, data="close_cancel")
    context = make_context(secrets=secrets)

    asyncio.run(on_close_callback(update, context))

    update.callback_query.edit_message_text.assert_called_once_with("Cancelado.")


def test_on_close_callback_pick_shows_confirmation():
    secrets = make_secrets()
    config = make_config()
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.5, entry_price=50000.0)
    client = MagicMock()
    update = make_callback_update(chat_id=AUTHORIZED_CHAT_ID, data="close_pick:BTC/USDT")
    context = make_context(secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=position):
        asyncio.run(on_close_callback(update, context))

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "BTC" in text and "Esta acción no se puede deshacer" in text


def test_on_close_callback_confirm_already_flat():
    secrets = make_secrets()
    config = make_config()
    flat = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    client = MagicMock()
    update = make_callback_update(chat_id=AUTHORIZED_CHAT_ID, data="close_confirm:BTC/USDT")
    context = make_context(secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=flat):
        asyncio.run(on_close_callback(update, context))

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "Ya no hay posición abierta" in text


def test_on_close_callback_confirm_executes_close_and_records_history():
    secrets = make_secrets()
    config = make_config()
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.5, entry_price=50000.0)
    client = MagicMock()
    result = OrderResult(
        symbol="BTC/USDT", action="close", entry_order={"id": "1"}, stop_order=None,
        filled_quantity=1.5, filled_price=51000.0, realized_pnl=1500.0,
    )
    update = make_callback_update(chat_id=AUTHORIZED_CHAT_ID, data="close_confirm:BTC/USDT")
    context = make_context(secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=position), \
         patch("autotrading.telegram_bot.close_position", return_value=result) as mock_close, \
         patch("autotrading.telegram_bot.trade_history.record_closed_trade") as mock_record, \
         patch("autotrading.telegram_bot.position_tracking.untrack_position") as mock_untrack:
        asyncio.run(on_close_callback(update, context))

    mock_close.assert_called_once_with(client, "BTC/USDT", position, "USDT")
    assert mock_record.call_args.kwargs["closed_via"] == "bot"
    mock_untrack.assert_called_once_with(secrets, "BTC/USDT")
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "BTC" in text and "+1500.0000" in text


def test_on_close_callback_confirm_reports_order_failure():
    secrets = make_secrets()
    config = make_config()
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.5, entry_price=50000.0)
    client = MagicMock()
    update = make_callback_update(chat_id=AUTHORIZED_CHAT_ID, data="close_confirm:BTC/USDT")
    context = make_context(secrets=secrets, config=config, client=client)

    with patch("autotrading.telegram_bot.get_position_state", return_value=position), \
         patch("autotrading.telegram_bot.close_position", side_effect=Exception("insufficient margin")):
        asyncio.run(on_close_callback(update, context))

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "FALLÓ" in text


def test_cmd_settings_shows_yaml_defaults_when_no_override():
    secrets = make_secrets()
    config = make_config(leverage=4, position_size_pct=0.04)
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config)
    state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=None)

    with patch("autotrading.telegram_bot.fetch_bot_state", return_value=state):
        asyncio.run(cmd_settings(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "4x" in text and "sin override" in text
    assert "4.0%" in text


def test_cmd_settings_shows_active_override():
    secrets = make_secrets()
    config = make_config(leverage=4, position_size_pct=0.04)
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config)
    state = BotState(
        bot_enabled=True, run_interval_minutes=60, last_run_at=None,
        leverage=7, position_size_pct=0.1,
    )

    with patch("autotrading.telegram_bot.fetch_bot_state", return_value=state):
        asyncio.run(cmd_settings(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "7x" in text and "override activo" in text
    assert "10.0%" in text


def test_cmd_set_leverage_valid_value():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["7"], secrets=secrets)

    with patch("autotrading.telegram_bot.set_leverage") as mock_set:
        asyncio.run(cmd_set_leverage(update, context))

    mock_set.assert_called_once_with(secrets, 7)
    text = update.message.reply_text.call_args.args[0]
    assert "7x" in text


def test_cmd_set_leverage_rejects_unsafe_value():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["50"], secrets=secrets)

    with patch("autotrading.telegram_bot.set_leverage") as mock_set:
        asyncio.run(cmd_set_leverage(update, context))

    mock_set.assert_not_called()
    text = update.message.reply_text.call_args.args[0]
    assert "inválido" in text.lower()


def test_cmd_set_leverage_default_clears_override():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["default"], secrets=secrets)

    with patch("autotrading.telegram_bot.set_leverage") as mock_set:
        asyncio.run(cmd_set_leverage(update, context))

    mock_set.assert_called_once_with(secrets, None)


def test_cmd_set_risk_valid_value():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["4"], secrets=secrets)

    with patch("autotrading.telegram_bot.set_position_size_pct") as mock_set:
        asyncio.run(cmd_set_risk(update, context))

    mock_set.assert_called_once()
    assert mock_set.call_args.args[1] == pytest.approx(0.04)


def test_cmd_set_risk_rejects_unsafe_value():
    secrets = make_secrets()
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(args=["90"], secrets=secrets)

    with patch("autotrading.telegram_bot.set_position_size_pct") as mock_set:
        asyncio.run(cmd_set_risk(update, context))

    mock_set.assert_not_called()
    text = update.message.reply_text.call_args.args[0]
    assert "inválido" in text.lower()


def test_notify_does_nothing_when_not_configured():
    secrets = make_secrets(bot_token=None)
    with patch("autotrading.telegram_bot.Bot") as mock_bot_cls:
        notify(secrets, "hola")
    mock_bot_cls.assert_not_called()


def test_notify_sends_message_when_configured():
    secrets = make_secrets()
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("autotrading.telegram_bot.Bot", return_value=mock_bot) as mock_bot_cls:
        notify(secrets, "hola")

    mock_bot_cls.assert_called_once_with(token="tok")
    mock_bot.send_message.assert_called_once_with(chat_id=AUTHORIZED_CHAT_ID, text="hola")


def test_notify_swallows_send_failures():
    secrets = make_secrets()
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=Exception("network down"))

    with patch("autotrading.telegram_bot.Bot", return_value=mock_bot):
        notify(secrets, "hola")  # should not raise


@pytest.mark.parametrize(
    "value,expected",
    [
        (50000.0, "50000"),  # not "5e+04"
        (6688.8, "6688.8"),
        (1.5, "1.5"),
        (0.1195, "0.1195"),
        (0.0, "0"),
    ],
)
def test_fmt_num_never_uses_scientific_notation(value, expected):
    assert _fmt_num(value) == expected
