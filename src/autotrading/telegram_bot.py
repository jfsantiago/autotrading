from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot, BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from autotrading import trade_history
from autotrading.config import AppConfig
from autotrading.execution.client import to_futures_symbol
from autotrading.scheduling import fetch_bot_state
from autotrading.secrets import Secrets

logger = logging.getLogger(__name__)


def require_telegram_secrets(secrets: Secrets) -> None:
    if not secrets.telegram_bot_token or not secrets.telegram_chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set. Create a bot via "
            "@BotFather and get your numeric chat id from @userinfobot, then add "
            "them to .env."
        )


def _is_authorized(chat_id: int, allowed_chat_id: int) -> bool:
    return chat_id == allowed_chat_id


async def _guarded(update: Update, secrets: Secrets) -> bool:
    """Second layer of access control, redundant with the per-handler
    filters.Chat() filter by design — so a future handler registered
    without that filter still fails closed, not open. Unauthorized senders
    get silence, not even a "not authorized" reply.
    """
    chat = update.effective_chat
    if chat is None or not _is_authorized(chat.id, secrets.telegram_chat_id):
        return False
    return True


def _fetch_open_positions_with_pnl(
    client: Any, symbols: list[str], quote_currency: str
) -> list[dict[str, Any]]:
    futures_symbols = [to_futures_symbol(s, quote_currency) for s in symbols]
    raw_positions = client.fetch_positions(futures_symbols)
    by_futures_symbol = {p.get("symbol"): p for p in raw_positions}

    open_positions = []
    for symbol, futures_symbol in zip(symbols, futures_symbols):
        position = by_futures_symbol.get(futures_symbol)
        if position is None or not (position.get("contracts") or 0):
            continue
        open_positions.append(
            {
                "symbol": symbol,
                "side": position.get("side"),
                "size": abs(position.get("contracts")),
                "entry_price": position.get("entryPrice"),
                "unrealized_pnl": position.get("unrealizedPnl"),
            }
        )
    return open_positions


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return
    await update.message.reply_text(
        "AutoTrading — bot de solo lectura\n\n"
        "Toca el botón de menú (☰ junto al campo de texto) para ver los "
        "comandos disponibles:\n\n"
        "/positions — posiciones abiertas ahora\n"
        "/history — últimos cierres y su PnL\n"
        "/status — estado del bot (encendido/apagado, intervalo)"
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    config: AppConfig = context.bot_data["config"]
    client = context.bot_data["client"]

    positions = _fetch_open_positions_with_pnl(
        client, config.all_symbols, config.futures.quote_currency
    )
    if not positions:
        await update.message.reply_text("Sin posiciones abiertas ahora mismo.")
        return

    header = f"{'Symbol':<9}{'Lado':<5}{'Cant.':>9}{'Entrada':>10}{'PnL no real.':>13}"
    rows = [header, "-" * len(header)]
    for p in positions:
        pnl = p["unrealized_pnl"]
        pnl_str = f"{pnl:+.4f}" if pnl is not None else "?"
        rows.append(
            f"{p['symbol']:<9}{p['side']:<5}{p['size']:>9.4g}"
            f"{p['entry_price']:>10.4g}{pnl_str:>13}"
        )
    table = "\n".join(rows)
    await update.message.reply_text(
        f"Posiciones abiertas:\n<pre>{table}</pre>", parse_mode=ParseMode.HTML
    )


def _format_trades_table(trades: list) -> str:
    # Monospace table via <pre> — Telegram has no native table widget, but a
    # fixed-width font makes columns line up. General-format (%g) for
    # prices/qty since values span from ~$90k (BTC) to ~$0.000001-scale
    # tokens; a fixed decimal count would break at one end or the other.
    header = f"{'Symbol':<9}{'Lado':<5}{'Cant.':>9}{'Entrada':>10}{'Salida':>10}{'PnL':>9}{'Fecha':>12}"
    rows = [header, "-" * len(header)]
    for t in trades:
        pnl_str = f"{t.realized_pnl:+.4f}" if t.realized_pnl is not None else "?"
        exit_str = f"{t.exit_price:.4g}" if t.exit_price is not None else "?"
        date_str = t.closed_at.strftime("%m-%d %H:%M")
        rows.append(
            f"{t.symbol:<9}{t.position_side:<5}{t.quantity:>9.4g}"
            f"{t.entry_price:>10.4g}{exit_str:>10}{pnl_str:>9}{date_str:>12}"
        )
    return "\n".join(rows)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    trades = trade_history.fetch_recent_closed_trades(secrets, limit=10)
    if not trades:
        await update.message.reply_text("Sin cierres registrados todavía.")
        return

    table = _format_trades_table(trades)
    await update.message.reply_text(
        f"Últimos cierres:\n<pre>{table}</pre>", parse_mode=ParseMode.HTML
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    state = fetch_bot_state(secrets)
    status = "ENCENDIDO" if state.bot_enabled else "APAGADO"
    last_run = (
        state.last_run_at.strftime("%Y-%m-%d %H:%M UTC") if state.last_run_at else "nunca"
    )
    await update.message.reply_text(
        f"Bot: {status}\nIntervalo: {state.run_interval_minutes} min\nÚltima corrida: {last_run}"
    )


async def _set_command_menu(application: Application) -> None:
    """Populates Telegram's native "/" command menu — a single button next
    to the message box that expands into the full command list, instead of
    several always-visible reply-keyboard buttons taking up screen space.
    """
    await application.bot.set_my_commands(
        [
            BotCommand("positions", "Posiciones abiertas ahora"),
            BotCommand("history", "Últimos cierres y su PnL"),
            BotCommand("status", "Estado del bot"),
            BotCommand("start", "Mostrar el menú de botones"),
        ]
    )


def notify(secrets: Secrets, text: str) -> None:
    """Best-effort one-off notification, independent of the long-running
    polling bot — `scheduled-run` is a oneshot process, it can't run
    run_polling(). Silently does nothing if Telegram isn't configured
    (it's optional for every other command); never raises on a send
    failure, since a notification hiccup must not make an already-finished
    trading cycle look like it failed.
    """
    if not secrets.telegram_bot_token or not secrets.telegram_chat_id:
        return
    try:
        asyncio.run(
            Bot(token=secrets.telegram_bot_token).send_message(
                chat_id=secrets.telegram_chat_id, text=text
            )
        )
    except Exception:
        logger.warning("failed to send Telegram notification", exc_info=True)


def run(config: AppConfig, secrets: Secrets, client: Any) -> None:
    require_telegram_secrets(secrets)

    application = (
        Application.builder()
        .token(secrets.telegram_bot_token)
        .post_init(_set_command_menu)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["secrets"] = secrets
    application.bot_data["client"] = client

    auth_filter = filters.Chat(chat_id=secrets.telegram_chat_id)
    application.add_handler(CommandHandler(["start", "help"], cmd_start, filters=auth_filter))
    application.add_handler(CommandHandler("positions", cmd_positions, filters=auth_filter))
    application.add_handler(CommandHandler("history", cmd_history, filters=auth_filter))
    application.add_handler(CommandHandler("status", cmd_status, filters=auth_filter))

    logger.info("Telegram bot starting (long polling)")
    application.run_polling()
