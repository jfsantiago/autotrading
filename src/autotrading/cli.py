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
from autotrading.news.aggregate import aggregate_by_symbol
from autotrading.news.events import merge_events
from autotrading.news.llm_sentiment import classify_headlines_batch
from autotrading.news.macro_calendar import load_macro_events
from autotrading.news.models import ScoredItem
from autotrading.news.report import print_news_summary, save_news_results
from autotrading.news.scoring import label_to_score
from autotrading.news.sources.coinmarketcal import fetch_crypto_events
from autotrading.news.sources.newsdata import fetch_newsdata_items
from autotrading.news.sources.rss import fetch_rss_items
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


def run_news_command(args: argparse.Namespace) -> int:
    import openai

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config: AppConfig = load_config(args.config)
    if config.news is None:
        print("Error: this config file has no `news:` section configured.")
        return 1

    try:
        secrets = load_secrets()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    news_cfg = config.news
    cache_dir = Path(news_cfg.cache.dir)
    output_dir = Path(args.output or news_cfg.output.dir)

    rss_items = fetch_rss_items(news_cfg.rss.feeds, news_cfg.rss.fetch_limit_per_feed)

    newsdata_items = []
    if news_cfg.newsdata.enabled:
        newsdata_items = fetch_newsdata_items(
            secrets, config.all_symbols, cache_dir, news_cfg.cache.raw_ttl_hours
        )

    crypto_events = []
    if news_cfg.calendar.crypto_events_enabled:
        crypto_events = fetch_crypto_events(
            secrets,
            config.all_symbols,
            news_cfg.calendar.lookahead_days,
            cache_dir,
            news_cfg.cache.raw_ttl_hours,
        )
    macro_events = load_macro_events(news_cfg.calendar.macro_events_file)

    client = openai.OpenAI(api_key=secrets.openai_api_key)
    classifications = classify_headlines_batch(
        client,
        rss_items,
        config.all_symbols,
        cache_dir,
        news_cfg.sentiment.llm_model,
        news_cfg.sentiment.llm_batch_size,
    )

    scored_items: list[ScoredItem] = []
    for item in rss_items:
        classification = classifications[item.item_id]
        scored_items.append(
            ScoredItem(
                item=item,
                label=classification.label,
                score=label_to_score(classification.label),
                symbols=classification.relevant_symbols,
                source_weight=news_cfg.sentiment.llm_source_weight,
            )
        )
    for item in newsdata_items:
        label = item.native_label
        scored_items.append(
            ScoredItem(
                item=item,
                label=label,
                score=label_to_score(label),
                symbols=item.native_symbols or [],
                source_weight=news_cfg.newsdata.source_weight,
            )
        )

    symbol_sentiments = aggregate_by_symbol(scored_items, config.all_symbols)
    upcoming_events = merge_events(
        crypto_events, macro_events, news_cfg.calendar.soon_threshold_days
    )

    print_news_summary(symbol_sentiments, upcoming_events)
    if news_cfg.output.save_csv:
        save_news_results(scored_items, symbol_sentiments, upcoming_events, output_dir)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "backtest":
        return run_backtest_command(args)
    if args.command == "news":
        return run_news_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
