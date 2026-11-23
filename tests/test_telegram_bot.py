import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autotrading.scheduling import BotState
from autotrading.secrets import Secrets
from autotrading.telegram_bot import (
    _fmt_num,
    _is_authorized,
    cmd_history,
    cmd_positions,
    cmd_status,
    notify,
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


def make_context(**bot_data):
    context = MagicMock()
    context.bot_data = bot_data
    return context


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
            }
        ]
    )
    update = make_update(chat_id=AUTHORIZED_CHAT_ID)
    context = make_context(secrets=secrets, config=config, client=client)

    asyncio.run(cmd_positions(update, context))

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert "BTC" in text  # base ticker only, "/USDT" dropped for table width
    assert "50000" in text  # not scientific notation ("5e+04")
    assert "25" in text


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
        closed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    with patch(
        "autotrading.telegram_bot.trade_history.fetch_recent_closed_trades",
        return_value=[trade],
    ):
        asyncio.run(cmd_history(update, context))

    text = update.message.reply_text.call_args.args[0]
    assert "BTC" in text  # base ticker only, "/USDT" dropped for table width
    assert "10.0" in text or "+10.0000" in text
    assert "20260101:1200" in text  # date format "YYYYMMDD:HHMM"
    assert "largo" in text  # "long" translated for display


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
