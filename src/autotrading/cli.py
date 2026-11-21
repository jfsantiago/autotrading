from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from autotrading.config import AppConfig, load_config
from autotrading.data.cache import get_cached_ohlcv
from autotrading.data.exchange import fetch_ohlcv_range, make_public_client
from autotrading.engine.backtester import run_backtest
from autotrading.reporting.report import report
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


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "backtest":
        return run_backtest_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
