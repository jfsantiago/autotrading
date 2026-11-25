from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from autotrading import position_tracking, trade_history
from autotrading.config import (
    TAKE_PROFIT_TO_STOP_LOSS_RATIO,
    AppConfig,
    assert_position_size_safe,
    assert_take_profit_margin_safe,
)
from autotrading.execution.client import assert_leverage_safe, to_futures_symbol
from autotrading.execution.orders import close_position
from autotrading.execution.positions import PositionSide, PositionState, get_position_state
from autotrading.scheduling import (
    assert_run_interval_safe,
    fetch_bot_state,
    set_bot_enabled,
    set_leverage,
    set_position_size_pct,
    set_run_interval_minutes,
    set_take_profit_margin_pct,
)
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
                "margin": position.get("initialMargin"),
            }
        )
    return open_positions


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return
    await update.message.reply_text(
        "AutoTrading\n\n"
        "Toca el botón de menú (☰ junto al campo de texto) para ver los "
        "comandos disponibles:\n\n"
        "/positions — posiciones abiertas ahora\n"
        "/universe — criptos que el bot evalúa en cada revisión\n"
        "/history — últimos cierres y su PnL\n"
        "/balance — saldo total de la cuenta\n"
        "/close — cerrar una posición abierta manualmente\n"
        "/status — estado del bot (encendido/apagado, intervalo)\n"
        "/pause — detener el bot de emergencia (no abre más operaciones)\n"
        "/resume — reanudar el bot después de un /pause\n"
        "/settings — apalancamiento y tamaño de posición actuales\n"
        "/set_leverage — cambiar el apalancamiento\n"
        "/set_risk — cambiar el tamaño de posición\n"
        "/set_take_profit — cambiar el take-profit (el stop-loss se ajusta junto)\n"
        "/set_interval — cambiar cada cuánto revisa el bot"
    )


def _fmt_num(value: float) -> str:
    """Fixed-point formatting, never scientific notation — %g switched to
    "5e+04" for a $50,000 BTC entry price, confusing for a non-technical
    reader. Large values get 2 decimals, small ones (sub-cent crypto
    prices) get up to 8, then trailing zeros are trimmed either way.
    """
    text = f"{value:.2f}" if abs(value) >= 1 else f"{value:.8f}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


_SIDE_LABELS = {"long": "buy", "short": "sell"}


def _fmt_side(side: str) -> str:
    """long/short (the stored values) -> buy/sell for display, matching
    Binance's own terminology (requested directly, after "largo"/"corto"
    caused confusion about which maps to which direction)."""
    return _SIDE_LABELS.get(side, side)


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

    # Fecha de apertura no viene del propio fetch_positions de Binance (no
    # trae un timestamp de apertura confiable) — sale de nuestra propia
    # tabla de tracking, la misma que usa la detección de stop-loss.
    tracked = position_tracking.fetch_all_tracked_positions(secrets)

    # "Cant." muestra el margen real en USDT puesto de la cuenta (lo que de
    # verdad se arriesgó), no la cantidad del activo ni el notional
    # apalancado — eso es lo que se confundía antes.
    header = f"{'Symbol':<8}{'Lado':<6}{'Cant.':>9}{'PnL':>10}{'Fecha':>12}"
    rows = [header, "-" * len(header)]
    for p in positions:
        pnl = p["unrealized_pnl"]
        pnl_str = f"{pnl:+.4f}" if pnl is not None else "?"
        base_symbol = p["symbol"].split("/")[0]
        margin_str = _fmt_num(p["margin"]) if p["margin"] is not None else "?"
        tracked_position = tracked.get(p["symbol"])
        date_str = (
            tracked_position.opened_at.strftime("%y%m%d:%H%M") if tracked_position else "?"
        )
        rows.append(
            f"{base_symbol:<8}{_fmt_side(p['side']):<6}{margin_str:>9}"
            f"{pnl_str:>10}{date_str:>12}"
        )

    total_margin = sum(p["margin"] for p in positions if p["margin"] is not None)
    total_pnl = sum(p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None)
    total_pnl_str = f"{total_pnl:+.4f}"
    rows.append("-" * len(header))
    rows.append(f"{'TOTAL':<8}{'':<6}{_fmt_num(total_margin):>9}{total_pnl_str:>10}{'':>12}")
    table = "\n".join(rows)
    await update.message.reply_text(
        f"Posiciones abiertas:\n<pre>{table}</pre>", parse_mode=ParseMode.HTML
    )


_STRATEGY_LABELS = {
    "stable_trend": "tendencia (cruce de medias + RSI)",
    "volatile_breakout": "ruptura (momentum + volumen)",
}


async def cmd_universe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    config: AppConfig = context.bot_data["config"]

    def format_bucket(name: str, symbols: list[str], strategy: str) -> str:
        symbol_list = ", ".join(s.split("/")[0] for s in symbols)
        strategy_label = _STRATEGY_LABELS.get(strategy, strategy)
        return f"{name} ({strategy_label}):\n{symbol_list}"

    text = "\n\n".join(
        [
            format_bucket("Estables", config.stable.symbols, config.stable.strategy),
            format_bucket("Volátiles", config.volatile.symbols, config.volatile.strategy),
        ]
    )
    await update.message.reply_text(text)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    config: AppConfig = context.bot_data["config"]
    client = context.bot_data["client"]
    quote = config.futures.quote_currency
    balance = client.fetch_balance().get(quote, {})

    def fmt(key: str) -> str:
        value = balance.get(key)
        return _fmt_num(value) if value is not None else "?"

    await update.message.reply_text(
        f"Saldo total: {fmt('total')} {quote}\n"
        f"Disponible: {fmt('free')} {quote}\n"
        f"En uso (margen): {fmt('used')} {quote}"
    )


def _build_close_confirmation(position: PositionState) -> tuple[str, InlineKeyboardMarkup]:
    base_symbol = position.symbol.split("/")[0]
    pnl = position.unrealized_pnl
    pnl_str = f"{pnl:+.4f}" if pnl is not None else "?"
    text = (
        f"¿Seguro que quieres cerrar {base_symbol}? PnL actual: {pnl_str}\n"
        "Esta acción no se puede deshacer."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Sí, cerrar", callback_data=f"close_confirm:{position.symbol}"),
                InlineKeyboardButton("Cancelar", callback_data="close_cancel"),
            ]
        ]
    )
    return text, keyboard


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    config: AppConfig = context.bot_data["config"]
    client = context.bot_data["client"]

    if context.args:
        arg = context.args[0].upper()
        symbol = arg if "/" in arg else f"{arg}/{config.futures.quote_currency}"
        if symbol not in config.all_symbols:
            await update.message.reply_text(f"Símbolo no reconocido: {context.args[0]}")
            return
        position = get_position_state(client, symbol, config.futures.quote_currency)
        if position.side == PositionSide.FLAT:
            await update.message.reply_text(f"No hay posición abierta en {arg}.")
            return
        text, markup = _build_close_confirmation(position)
        await update.message.reply_text(text, reply_markup=markup)
        return

    # No symbol given — list every open position as its own button, so
    # there's nothing to type and no way to pick the wrong one.
    positions = _fetch_open_positions_with_pnl(
        client, config.all_symbols, config.futures.quote_currency
    )
    if not positions:
        await update.message.reply_text("No hay posiciones abiertas.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Cerrar {p['symbol'].split('/')[0]} — {_fmt_side(p['side'])}, "
                    f"{_fmt_num(p['size'])}",
                    callback_data=f"close_pick:{p['symbol']}",
                )
            ]
            for p in positions
        ]
    )
    await update.message.reply_text("¿Cuál posición quieres cerrar?", reply_markup=keyboard)


async def on_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single access-control layer for this handler — CallbackQueryHandler
    has no filters.Chat() equivalent to pair with, unlike the CommandHandler
    registrations, so _guarded() alone has to hold the line here.
    """
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    query = update.callback_query
    await query.answer()

    if query.data == "close_cancel":
        await query.edit_message_text("Cancelado.")
        return

    action, _, symbol = query.data.partition(":")
    config: AppConfig = context.bot_data["config"]
    client = context.bot_data["client"]

    # Re-check live state rather than trust what was shown when the button
    # was first sent — it may have closed (stop-loss, or a second tap) in
    # between.
    position = get_position_state(client, symbol, config.futures.quote_currency)
    if position.side == PositionSide.FLAT:
        await query.edit_message_text(f"Ya no hay posición abierta en {symbol.split('/')[0]}.")
        return

    if action == "close_pick":
        text, markup = _build_close_confirmation(position)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if action == "close_confirm":
        try:
            result = close_position(client, symbol, position, config.futures.quote_currency)
            trade_history.record_closed_trade(
                secrets,
                symbol=symbol,
                position_side=position.side.value,
                quantity=position.size,
                entry_price=position.entry_price,
                exit_price=result.filled_price,
                realized_pnl=result.realized_pnl,
                closed_via="bot",
                margin=position.margin,
            )
            position_tracking.untrack_position(secrets, symbol)
        except Exception as exc:
            logger.warning("manual close failed for %s", symbol, exc_info=True)
            await query.edit_message_text(f"ORDEN FALLÓ — {symbol.split('/')[0]}: {exc}")
            return

        pnl = result.realized_pnl
        pnl_str = f"{pnl:+.4f}" if pnl is not None else "?"
        price_str = _fmt_num(result.filled_price) if result.filled_price is not None else "?"
        await query.edit_message_text(
            f"Cerrado {symbol.split('/')[0]} @ {price_str}\nPnL: {pnl_str}"
        )


def _format_trades_table(trades: list, total_margin: float, total_pnl: float) -> str:
    # Monospace table via <pre> — Telegram has no native table widget, but a
    # fixed-width font makes columns line up. Date format "YYMMDD:HHMM"
    # (2-digit year) per explicit request — no internal space (a space was
    # the earlier wrap point on narrow phone screens, confirmed live; ":"
    # doesn't trigger the same). "Cant." shows the real USDT margin
    # committed (pre-leverage), not asset quantity. "Vía" tells a
    # stop-loss-triggered close (fired directly on Binance, bypassing the
    # bot's own close logic) apart from one the bot decided on itself.
    #
    # total_margin/total_pnl come from fetch_closed_trades_totals() — a
    # separate query over ALL history, not just `trades` (whatever page is
    # being displayed) — otherwise the TOTAL row silently looks better than
    # reality once older losing trades scroll past the display limit.
    header = f"{'Symbol':<8}{'Lado':<6}{'Cant.':>9}{'PnL':>10}{'Vía':>5}{'Fecha':>12}"
    rows = [header, "-" * len(header)]
    for t in trades:
        pnl_str = f"{t.realized_pnl:+.4f}" if t.realized_pnl is not None else "?"
        date_str = t.closed_at.strftime("%y%m%d:%H%M")
        base_symbol = t.symbol.split("/")[0]
        via_str = {"stop_loss": "SL", "take_profit": "TP"}.get(t.closed_via, "bot")
        margin_str = _fmt_num(t.margin) if t.margin is not None else "?"
        rows.append(
            f"{base_symbol:<8}{_fmt_side(t.position_side):<6}"
            f"{margin_str:>9}{pnl_str:>10}{via_str:>5}{date_str:>12}"
        )

    total_pnl_str = f"{total_pnl:+.4f}"
    rows.append("-" * len(header))
    rows.append(
        f"{'TOTAL':<8}{'':<6}{_fmt_num(total_margin):>9}{total_pnl_str:>10}{'':>5}{'':>12}"
    )
    return "\n".join(rows)


HISTORY_DISPLAY_LIMIT = 30


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    trades = trade_history.fetch_recent_closed_trades(secrets, limit=HISTORY_DISPLAY_LIMIT)
    if not trades:
        await update.message.reply_text("Sin cierres registrados todavía.")
        return

    total_count, total_margin, total_pnl = trade_history.fetch_closed_trades_totals(secrets)
    table = _format_trades_table(trades, total_margin, total_pnl)

    header = "Últimos cierres:"
    if total_count > len(trades):
        header = f"Últimos {len(trades)} cierres (de {total_count} en total):"
    await update.message.reply_text(f"{header}\n<pre>{table}</pre>", parse_mode=ParseMode.HTML)


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


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Emergency stop: flips bot_enabled off, which run_scheduled_command
    checks before doing anything else — the next heartbeat skips entirely,
    no API calls, no new positions. Does NOT touch positions already open;
    their stop-loss keeps resting on Binance independently of this bot
    process running or not.
    """
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    set_bot_enabled(secrets, False)
    await update.message.reply_text(
        "Bot PAUSADO. No se abrirán operaciones nuevas hasta que uses /resume.\n"
        "Las posiciones ya abiertas siguen con su stop-loss activo en Binance, "
        "esto no las cierra ni las desprotege."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    set_bot_enabled(secrets, True)
    await update.message.reply_text("Bot REANUDADO. Vuelve a revisar y operar normalmente.")


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    config: AppConfig = context.bot_data["config"]
    state = fetch_bot_state(secrets)

    if state.leverage is not None:
        leverage_line = f"Apalancamiento: {state.leverage}x (override activo)"
    else:
        leverage_line = f"Apalancamiento: {config.futures.leverage}x (valor del YAML, sin override)"

    if state.position_size_pct is not None:
        risk_line = f"Tamaño de posición: {state.position_size_pct * 100:.1f}% (override activo)"
    else:
        risk_line = (
            f"Tamaño de posición: {config.risk.position_size_pct * 100:.1f}% "
            "(valor del YAML, sin override)"
        )

    if state.take_profit_margin_pct is not None:
        take_profit_pct = state.take_profit_margin_pct
        source = "override activo"
    else:
        take_profit_pct = config.risk.take_profit_margin_pct
        source = "valor del YAML, sin override"
    stop_loss_pct = take_profit_pct / TAKE_PROFIT_TO_STOP_LOSS_RATIO
    tp_line = (
        f"Take-profit: {take_profit_pct * 100:.1f}% de margen real ({source})\n"
        f"Stop-loss: {stop_loss_pct * 100:.1f}% de margen real (siempre la mitad del take-profit)"
    )

    await update.message.reply_text(f"{leverage_line}\n{risk_line}\n{tp_line}")


async def cmd_set_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    if not context.args:
        await update.message.reply_text("Uso: /set_leverage <1-10> o /set_leverage default")
        return

    arg = context.args[0].lower()
    if arg == "default":
        set_leverage(secrets, None)
        await update.message.reply_text("Apalancamiento: override eliminado, vuelve a usar el YAML.")
        return

    try:
        value = int(arg)
        assert_leverage_safe(value)
    except ValueError as exc:
        await update.message.reply_text(f"Valor inválido: {exc}")
        return

    set_leverage(secrets, value)
    await update.message.reply_text(
        f"Apalancamiento actualizado a {value}x. Se aplicará a la próxima posición que se "
        "abra (no afecta una posición ya abierta)."
    )


async def cmd_set_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    if not context.args:
        await update.message.reply_text("Uso: /set_risk <porcentaje, ej. 4> o /set_risk default")
        return

    arg = context.args[0].lower()
    if arg == "default":
        set_position_size_pct(secrets, None)
        await update.message.reply_text(
            "Tamaño de posición: override eliminado, vuelve a usar el YAML."
        )
        return

    try:
        value = float(arg) / 100
        assert_position_size_safe(value)
    except ValueError as exc:
        await update.message.reply_text(f"Valor inválido: {exc}")
        return

    set_position_size_pct(secrets, value)
    await update.message.reply_text(
        f"Tamaño de posición actualizado a {value * 100:.1f}%. Se aplicará a la próxima "
        "posición que se abra."
    )


async def cmd_set_take_profit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets take_profit_margin_pct — stop_loss_margin_pct always derives as
    half of it (see RiskParameters.stop_loss_margin_pct), so there's no
    separate command to set the stop-loss independently; it moves with this
    one, keeping the validated 1:2 risk/reward ratio intact.
    """
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    if not context.args:
        await update.message.reply_text(
            "Uso: /set_take_profit <porcentaje de margen, ej. 24> o /set_take_profit default"
        )
        return

    arg = context.args[0].lower()
    if arg == "default":
        set_take_profit_margin_pct(secrets, None)
        await update.message.reply_text(
            "Take-profit: override eliminado, vuelve a usar el YAML."
        )
        return

    try:
        value = float(arg) / 100
        assert_take_profit_margin_safe(value)
    except ValueError as exc:
        await update.message.reply_text(f"Valor inválido: {exc}")
        return

    set_take_profit_margin_pct(secrets, value)
    stop_loss_pct = value / TAKE_PROFIT_TO_STOP_LOSS_RATIO
    await update.message.reply_text(
        f"Take-profit actualizado a {value * 100:.1f}% de margen real.\n"
        f"Stop-loss se ajustó junto, a {stop_loss_pct * 100:.1f}% (siempre la mitad), "
        "para mantener la proporción 1:2.\n"
        "Se aplicará a la próxima posición que se abra, no a una ya abierta."
    )


async def cmd_set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Changes bot_state.run_interval_minutes — how often a heartbeat tick
    actually runs the full trade check (the heartbeat itself ticks every 5
    minutes regardless, via systemd; this just gates how many of those
    ticks do anything). No "default" keyword here — unlike leverage/risk/
    take-profit, this value has never lived in the YAML, only in bot_state.
    """
    secrets: Secrets = context.bot_data["secrets"]
    if not await _guarded(update, secrets):
        return

    if not context.args:
        await update.message.reply_text("Uso: /set_interval <minutos, ej. 30>")
        return

    try:
        minutes = int(context.args[0])
        assert_run_interval_safe(minutes)
    except ValueError as exc:
        await update.message.reply_text(f"Valor inválido: {exc}")
        return

    set_run_interval_minutes(secrets, minutes)
    await update.message.reply_text(
        f"Intervalo de revisión actualizado a {minutes} min. Se aplica desde la próxima vez "
        "que el bot revise (no fuerza una revisión inmediata)."
    )


async def _set_command_menu(application: Application) -> None:
    """Populates Telegram's native "/" command menu — a single button next
    to the message box that expands into the full command list, instead of
    several always-visible reply-keyboard buttons taking up screen space.
    """
    await application.bot.set_my_commands(
        [
            BotCommand("positions", "Posiciones abiertas ahora"),
            BotCommand("universe", "Criptos que el bot evalúa"),
            BotCommand("history", "Últimos cierres y su PnL"),
            BotCommand("balance", "Saldo total de la cuenta"),
            BotCommand("close", "Cerrar una posición abierta"),
            BotCommand("status", "Estado del bot"),
            BotCommand("pause", "Detener el bot de emergencia"),
            BotCommand("resume", "Reanudar el bot"),
            BotCommand("settings", "Apalancamiento y tamaño de posición"),
            BotCommand("set_leverage", "Cambiar el apalancamiento"),
            BotCommand("set_risk", "Cambiar el tamaño de posición"),
            BotCommand("set_take_profit", "Cambiar el take-profit"),
            BotCommand("set_interval", "Cambiar cada cuánto revisa el bot"),
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
    application.add_handler(CommandHandler("universe", cmd_universe, filters=auth_filter))
    application.add_handler(CommandHandler("history", cmd_history, filters=auth_filter))
    application.add_handler(CommandHandler("balance", cmd_balance, filters=auth_filter))
    application.add_handler(CommandHandler("close", cmd_close, filters=auth_filter))
    application.add_handler(CommandHandler("status", cmd_status, filters=auth_filter))
    application.add_handler(CommandHandler("pause", cmd_pause, filters=auth_filter))
    application.add_handler(CommandHandler("resume", cmd_resume, filters=auth_filter))
    application.add_handler(CommandHandler("settings", cmd_settings, filters=auth_filter))
    application.add_handler(CommandHandler("set_leverage", cmd_set_leverage, filters=auth_filter))
    application.add_handler(CommandHandler("set_risk", cmd_set_risk, filters=auth_filter))
    application.add_handler(
        CommandHandler("set_take_profit", cmd_set_take_profit, filters=auth_filter)
    )
    application.add_handler(CommandHandler("set_interval", cmd_set_interval, filters=auth_filter))
    application.add_handler(CallbackQueryHandler(on_close_callback, pattern=r"^close_"))

    logger.info("Telegram bot starting (long polling)")
    application.run_polling()
