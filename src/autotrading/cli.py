from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from autotrading.config import AppConfig, assert_position_size_safe, load_config
from autotrading.data.cache import get_cached_ohlcv
from autotrading.data.exchange import fetch_ohlcv_range, make_public_client
from autotrading.decision.engine import OrderAction, decide, decide_trade_action
from autotrading.decision.market import get_latest_signal
from autotrading.decision.report import print_decisions, save_decisions
from autotrading.engine.backtester import run_backtest
from autotrading.execution.client import assert_leverage_safe, make_futures_demo_client, to_futures_symbol
from autotrading.execution.orders import (
    calculate_position_size,
    close_position,
    fetch_realized_pnl,
    open_long,
    open_short,
)
from autotrading.execution.positions import PositionSide, get_position_state
from autotrading.execution.report import (
    print_confirm_footer,
    print_no_action,
    print_order_executed,
    print_trade_preview,
    save_trade_results,
)
from autotrading.news.pipeline import build_news_snapshot
from autotrading.news.report import print_news_summary, save_news_results
from autotrading.position_tracking import (
    fetch_all_tracked_positions,
    track_open_position,
    untrack_position,
)
from autotrading.reporting.report import report
from autotrading.scheduling import ensure_bot_state_row, fetch_bot_state, is_due, mark_run_completed
from autotrading.secrets import load_secrets
from autotrading.strategies import STRATEGY_REGISTRY
from autotrading.telegram_bot import notify as notify_telegram
from autotrading.telegram_bot import require_telegram_secrets
from autotrading.telegram_bot import run as run_telegram_bot
from autotrading.trade_history import record_closed_trade
from autotrading.utils.timeutils import parse_date_to_ms

logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autotrading")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest_parser = subparsers.add_parser("backtest", help="Run a historical backtest")
    backtest_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    backtest_parser.add_argument("--start", help="Override date_range.start (YYYY-MM-DD)")
    backtest_parser.add_argument("--end", help="Override date_range.end (YYYY-MM-DD)")
    backtest_parser.add_argument("--output", help="Override output.dir")

    news_parser = subparsers.add_parser("news", help="Fetch and score news/events")
    news_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    news_parser.add_argument("--output", help="Override news.output.dir")

    decide_parser = subparsers.add_parser(
        "decide", help="Dry-run: show what the bot would do right now (no orders placed)"
    )
    decide_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    decide_parser.add_argument("--output", help="Override results output dir for this run")

    trade_parser = subparsers.add_parser(
        "trade",
        help="Position-aware Binance Futures DEMO TRADING execution: preview, or place orders with --confirm",
    )
    trade_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    trade_parser.add_argument(
        "--confirm", action="store_true", help="Actually place orders on Binance Demo Trading"
    )
    trade_parser.add_argument("--symbol", help="Restrict to a single symbol (spot notation)")
    trade_parser.add_argument("--output", help="Override results output dir for this run")

    scheduled_parser = subparsers.add_parser(
        "scheduled-run",
        help="Kill-switch + due-check wrapper around `trade --confirm`, for cron/CI use",
    )
    scheduled_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    scheduled_parser.add_argument("--symbol", help="Restrict to a single symbol (spot notation)")
    scheduled_parser.add_argument("--output", help="Override results output dir for this run")
    scheduled_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force a preview-only trade run now, bypassing the kill switch and due-check "
        "(doesn't touch bot_state) — for verifying the pipeline from CI without risk",
    )

    telegram_parser = subparsers.add_parser(
        "telegram-bot",
        help="Run the read-only Telegram reporting bot (never returns, runs forever)",
    )
    telegram_parser.add_argument("--config", required=True, help="Path to a YAML config file")

    return parser


def run_backtest_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config: AppConfig = load_config(args.config)
    start = args.start or config.date_range.start
    end = args.end or config.date_range.end
    output_dir = Path(args.output or config.output.dir)

    since_ms = parse_date_to_ms(start)
    until_ms = parse_date_to_ms(end)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    if since_ms >= now_ms:
        print(f"Error: start date {start} is not in the past, no historical data available.")
        return 1
    if since_ms >= until_ms:
        print(f"Error: start date {start} must be before end date {end}.")
        return 1

    client = make_public_client()
    cache_dir = Path("data")

    symbol_data = {}
    signals = {}

    for symbol in config.all_symbols:
        df = get_cached_ohlcv(
            cache_dir,
            symbol,
            config.timeframe,
            since_ms,
            until_ms,
            fetch_fn=lambda s=symbol: fetch_ohlcv_range(
                client, s, config.timeframe, since_ms, until_ms
            ),
        )
        symbol_data[symbol] = df

        strategy_name = config.strategy_for_symbol(symbol)
        strategy = STRATEGY_REGISTRY[strategy_name]()
        params = config.strategy_params[strategy_name]
        signals[symbol] = strategy.generate_signals(df, params)

    portfolio = run_backtest(
        symbol_data, signals, config.initial_capital, config.risk, config.futures.leverage
    )
    report(portfolio, config.initial_capital, output_dir, config.output.save_csv)

    return 0


def _load_news_prerequisites(args: argparse.Namespace) -> tuple[AppConfig, object] | int:
    """Shared config/secrets loading + validation for `news` and `decide`.

    Returns (config, secrets) on success, or an int exit code on failure.
    """
    config: AppConfig = load_config(args.config)
    if config.news is None:
        print("Error: this config file has no `news:` section configured.")
        return 1

    try:
        secrets = load_secrets()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    return config, secrets


def run_news_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    loaded = _load_news_prerequisites(args)
    if isinstance(loaded, int):
        return loaded
    config, secrets = loaded

    output_dir = Path(args.output or config.news.output.dir)

    snapshot = build_news_snapshot(config, secrets)

    print_news_summary(snapshot.symbol_sentiments, snapshot.upcoming_events)
    if config.news.output.save_csv:
        save_news_results(
            snapshot.scored_items, snapshot.symbol_sentiments, snapshot.upcoming_events, output_dir
        )

    return 0


def run_decide_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    loaded = _load_news_prerequisites(args)
    if isinstance(loaded, int):
        return loaded
    config, secrets = loaded

    snapshot = build_news_snapshot(config, secrets)
    client = make_public_client()

    decisions = []
    for symbol in config.all_symbols:
        strategy_name = config.strategy_for_symbol(symbol)
        params = config.strategy_params[strategy_name]
        technical_signal, _ = get_latest_signal(
            client,
            symbol,
            config.timeframe,
            strategy_name,
            params,
            config.decision.live_lookback_candles,
        )
        news_sentiment = snapshot.symbol_sentiments.get(symbol)
        decisions.append(
            decide(symbol, technical_signal, news_sentiment, config.decision.news_veto_threshold)
        )

    print_decisions(decisions, snapshot.symbol_sentiments)

    output_dir = Path(args.output or "results/decide")
    save_decisions(decisions, snapshot.symbol_sentiments, output_dir)

    return 0


def _notify_review_summary(
    secrets, executed_results: dict[str, object], failed_symbols: list[tuple[str, str]]
) -> None:
    """Best-effort Telegram notification after a confirmed trade cycle —
    "did the system's review open/close anything?" No-op if Telegram isn't
    configured (notify() itself handles that); never raises.
    """
    lines = []
    for symbol, result in executed_results.items():
        if result.action == "close":
            pnl = result.realized_pnl
            pnl_str = f"{pnl:+.4f}" if pnl is not None else "?"
            lines.append(f"{symbol}: CLOSE @ {result.filled_price} (PnL {pnl_str})")
        else:
            lines.append(f"{symbol}: {result.action.upper()} @ {result.filled_price}")
    for symbol, error in failed_symbols:
        lines.append(f"{symbol}: FALLÓ ({error})")

    if lines:
        notify_telegram(secrets, "Revisión del bot:\n" + "\n".join(lines))
    else:
        notify_telegram(secrets, "Revisión del bot: sin operaciones nuevas.")


def _reconcile_stop_loss_closes(
    secrets, futures_client, config: AppConfig, symbols: list[str], positions_by_symbol: dict
) -> None:
    """Detect positions that closed on Binance's side (its own stop-loss
    order firing) without our code ever calling close_position — without
    this, those closes would never reach `closed_trades` or notify Telegram.
    Also self-heals: tracks any symbol that's live-open but not yet in
    `open_position_tracking` (first run after this feature shipped, or
    tracking that fell out of sync for any reason) using its current live
    entry_price/quantity, so future closes of it can be detected too.
    """
    tracked = fetch_all_tracked_positions(secrets)

    for symbol in symbols:
        position = positions_by_symbol[symbol]
        tracked_position = tracked.get(symbol)

        if position.side != PositionSide.FLAT:
            if tracked_position is None:
                track_open_position(
                    secrets, symbol=symbol, position_side=position.side.value,
                    quantity=position.size, entry_price=position.entry_price,
                )
            continue

        if tracked_position is None:
            continue  # flat and we already know it — nothing to reconcile

        # We think this symbol is open but Binance shows it flat and we
        # didn't close it ourselves this cycle — cross-check Binance's own
        # income history before concluding a stop-loss fired, so a
        # transient API glitch can't produce a false "closed" record.
        futures_symbol = to_futures_symbol(symbol, config.futures.quote_currency)
        since_ms = int(tracked_position.opened_at.timestamp() * 1000)
        realized_pnl = fetch_realized_pnl(futures_client, futures_symbol, since_ms)
        if realized_pnl is None:
            continue  # leave it tracked, retry on the next cycle

        # No order id to query the actual fill price for an externally
        # triggered close — reconstruct it algebraically from Binance's own
        # realized PnL figure instead: pnl = (exit - entry) * qty for a
        # long, (entry - exit) * qty for a short.
        sign = 1 if tracked_position.position_side == "long" else -1
        exit_price = tracked_position.entry_price + sign * realized_pnl / tracked_position.quantity

        try:
            record_closed_trade(
                secrets, symbol=symbol, position_side=tracked_position.position_side,
                quantity=tracked_position.quantity, entry_price=tracked_position.entry_price,
                exit_price=exit_price, realized_pnl=realized_pnl, closed_via="stop_loss",
            )
            untrack_position(secrets, symbol)
        except Exception as exc:
            print(f"WARNING: failed to record stop-loss close for {symbol}: {exc}")
            continue

        notify_telegram(
            secrets, f"{symbol}: cerrado por STOP-LOSS (automático), PnL {realized_pnl:+.4f}"
        )


def run_trade_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    loaded = _load_news_prerequisites(args)
    if isinstance(loaded, int):
        return loaded
    config, secrets = loaded

    # Telegram-adjustable overrides (/set_leverage, /set_risk) — NULL in
    # bot_state means "no override", keeping today's YAML/env behavior.
    # Applied here (not inside load_config) so config.py stays free of any
    # Supabase/secrets knowledge, same separation as everywhere else.
    ensure_bot_state_row(secrets)
    state = fetch_bot_state(secrets)
    if state.leverage is not None:
        config.futures.leverage = state.leverage
    if state.position_size_pct is not None:
        config.risk.position_size_pct = state.position_size_pct

    try:
        assert_leverage_safe(config.futures.leverage)
        assert_position_size_safe(config.risk.position_size_pct)
        futures_client = make_futures_demo_client(secrets)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        return 1

    spot_client = make_public_client()
    snapshot = build_news_snapshot(config, secrets)

    symbols = [args.symbol] if args.symbol else config.all_symbols

    decisions = []
    candles_by_symbol = {}
    positions_by_symbol = {}

    for symbol in symbols:
        strategy_name = config.strategy_for_symbol(symbol)
        params = config.strategy_params[strategy_name]
        technical_signal, df = get_latest_signal(
            spot_client,
            symbol,
            config.timeframe,
            strategy_name,
            params,
            config.decision.live_lookback_candles,
        )
        candles_by_symbol[symbol] = df

        position = get_position_state(futures_client, symbol, config.futures.quote_currency)
        positions_by_symbol[symbol] = position

        news_sentiment = snapshot.symbol_sentiments.get(symbol)
        decisions.append(
            decide_trade_action(
                symbol, technical_signal, position, news_sentiment, config.decision.news_veto_threshold
            )
        )

    print_trade_preview(decisions, snapshot.symbol_sentiments)

    executed_results = {}
    failed_symbols: list[tuple[str, str]] = []
    if args.confirm:
        _reconcile_stop_loss_closes(secrets, futures_client, config, symbols, positions_by_symbol)

        balance = futures_client.fetch_balance()
        equity = float(balance.get(config.futures.quote_currency, {}).get("total") or 0.0)

        for decision in decisions:
            if decision.order_action == OrderAction.NONE:
                print_no_action(decision)
                continue

            try:
                if decision.order_action == OrderAction.OPEN_LONG:
                    entry_price = candles_by_symbol[decision.symbol]["close"].iloc[-1]
                    quantity = calculate_position_size(
                        equity, entry_price, config.futures.leverage, config.risk
                    )
                    result = open_long(
                        futures_client, decision.symbol, quantity, config.futures.leverage,
                        config.risk.stop_loss_pct, config.futures.quote_currency,
                    )
                elif decision.order_action == OrderAction.OPEN_SHORT:
                    entry_price = candles_by_symbol[decision.symbol]["close"].iloc[-1]
                    quantity = calculate_position_size(
                        equity, entry_price, config.futures.leverage, config.risk
                    )
                    result = open_short(
                        futures_client, decision.symbol, quantity, config.futures.leverage,
                        config.risk.stop_loss_pct, config.futures.quote_currency,
                    )
                else:  # CLOSE_LONG or CLOSE_SHORT
                    result = close_position(
                        futures_client, decision.symbol, positions_by_symbol[decision.symbol],
                        config.futures.quote_currency,
                    )
            except Exception as exc:
                print(f"ORDER FAILED — {decision.symbol}: {exc}")
                failed_symbols.append((decision.symbol, str(exc)))
                continue

            executed_results[decision.symbol] = result
            print_order_executed(decision, result)

            if decision.order_action in (OrderAction.OPEN_LONG, OrderAction.OPEN_SHORT):
                position_side = "long" if decision.order_action == OrderAction.OPEN_LONG else "short"
                try:
                    track_open_position(
                        secrets, symbol=decision.symbol, position_side=position_side,
                        quantity=result.filled_quantity, entry_price=result.filled_price,
                    )
                except Exception as exc:
                    print(f"WARNING: failed to track open position for {decision.symbol}: {exc}")

            if decision.order_action in (OrderAction.CLOSE_LONG, OrderAction.CLOSE_SHORT):
                closed_position = positions_by_symbol[decision.symbol]
                try:
                    record_closed_trade(
                        secrets,
                        symbol=decision.symbol,
                        position_side=closed_position.side.value,
                        quantity=closed_position.size,
                        entry_price=closed_position.entry_price,
                        exit_price=result.filled_price,
                        realized_pnl=result.realized_pnl,
                    )
                    untrack_position(secrets, decision.symbol)
                except Exception as exc:
                    print(f"WARNING: failed to record trade history for {decision.symbol}: {exc}")

        _notify_review_summary(secrets, executed_results, failed_symbols)
        print_confirm_footer()

    output_dir = Path(args.output or "results/trade")
    save_trade_results(decisions, executed_results, output_dir)

    return 0


def run_scheduled_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        secrets = load_secrets()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    if args.dry_run:
        print("DRY RUN: bypassing kill switch / due-check. No orders placed; state not updated.")
        args.confirm = False
        return run_trade_command(args)

    ensure_bot_state_row(secrets)
    state = fetch_bot_state(secrets)

    if not state.bot_enabled:
        print("Bot disabled (bot_state.bot_enabled = false) — skipping, no API calls made.")
        return 0

    now = datetime.now(timezone.utc)
    if not is_due(state, now):
        print(
            f"Not due yet (last run {state.last_run_at}, interval "
            f"{state.run_interval_minutes}m) — skipping."
        )
        return 0

    args.confirm = True
    exit_code = run_trade_command(args)
    if exit_code == 0:
        mark_run_completed(secrets, now)
    return exit_code


def run_telegram_bot_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config: AppConfig = load_config(args.config)
    try:
        secrets = load_secrets()
        require_telegram_secrets(secrets)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    futures_client = make_futures_demo_client(secrets)
    run_telegram_bot(config, secrets, futures_client)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "backtest":
        return run_backtest_command(args)
    if args.command == "news":
        return run_news_command(args)
    if args.command == "decide":
        return run_decide_command(args)
    if args.command == "trade":
        return run_trade_command(args)
    if args.command == "scheduled-run":
        return run_scheduled_command(args)
    if args.command == "telegram-bot":
        return run_telegram_bot_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
