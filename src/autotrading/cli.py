from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from autotrading.config import AppConfig, load_config
from autotrading.data.cache import get_cached_ohlcv
from autotrading.data.exchange import fetch_ohlcv_range, make_public_client
from autotrading.decision.engine import OrderAction, decide, decide_trade_action
from autotrading.decision.market import get_latest_signal
from autotrading.decision.report import print_decisions, save_decisions
from autotrading.engine.backtester import run_backtest
from autotrading.execution.client import assert_leverage_safe, make_futures_testnet_client
from autotrading.execution.orders import calculate_position_size, close_position, open_long, open_short
from autotrading.execution.positions import get_position_state
from autotrading.execution.report import (
    print_confirm_footer,
    print_no_action,
    print_order_executed,
    print_trade_preview,
    save_trade_results,
)
from autotrading.news.pipeline import build_news_snapshot
from autotrading.news.report import print_news_summary, save_news_results
from autotrading.reporting.report import report
from autotrading.secrets import load_secrets
from autotrading.strategies import STRATEGY_REGISTRY
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
        help="Position-aware Binance Futures TESTNET execution: preview, or place orders with --confirm",
    )
    trade_parser.add_argument("--config", required=True, help="Path to a YAML config file")
    trade_parser.add_argument(
        "--confirm", action="store_true", help="Actually place orders on the Futures TESTNET"
    )
    trade_parser.add_argument("--symbol", help="Restrict to a single symbol (spot notation)")
    trade_parser.add_argument("--output", help="Override results output dir for this run")

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

    portfolio = run_backtest(symbol_data, signals, config.initial_capital, config.risk)
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


def run_trade_command(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    loaded = _load_news_prerequisites(args)
    if isinstance(loaded, int):
        return loaded
    config, secrets = loaded

    try:
        assert_leverage_safe(config.futures.leverage)
        futures_client = make_futures_testnet_client(secrets)
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
    if args.confirm:
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
                continue

            executed_results[decision.symbol] = result
            print_order_executed(decision, result)

        print_confirm_footer()

    output_dir = Path(args.output or "results/trade")
    save_trade_results(decisions, executed_results, output_dir)

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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
