from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from autotrading.news.config import NewsConfig, load_news_config


@dataclass
class RiskParameters:
    """Risk parameters for position sizing and exits.

    Loaded from YAML today; designed to be swappable for a future
    Telegram-driven runtime config without touching the engine.
    """

    position_size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    max_concurrent_positions: int
    fee_pct: float


@dataclass
class UniverseBucket:
    symbols: list[str]
    strategy: str


@dataclass
class DateRange:
    start: str
    end: str


@dataclass
class OutputConfig:
    dir: str
    save_csv: bool


DEFAULT_NEWS_VETO_THRESHOLD = -0.5
DEFAULT_LIVE_LOOKBACK_CANDLES = 300


@dataclass
class DecisionConfig:
    """Tuning for the live decision engine (`autotrading decide`).

    Always present with safe defaults (unlike `news`, which is opt-in) —
    there's no scenario where "decision is unconfigured" should mean
    "skip this feature," since `decide` is the feature being invoked.
    """

    news_veto_threshold: float
    live_lookback_candles: int


DEFAULT_FUTURES_LEVERAGE = 4
DEFAULT_FUTURES_QUOTE_CURRENCY = "USDT"


@dataclass
class FuturesConfig:
    """Futures trading tuning for `autotrading trade`. Always present with
    safe defaults, like `decision`. Margin mode is deliberately NOT here —
    it's hardcoded to isolated in execution/orders.py as a safety invariant,
    not something a config edit should be able to change.
    """

    leverage: int
    quote_currency: str


@dataclass
class AppConfig:
    exchange: str
    timeframe: str
    date_range: DateRange
    initial_capital: float
    stable: UniverseBucket
    volatile: UniverseBucket
    strategy_params: dict[str, dict[str, Any]]
    risk: RiskParameters
    output: OutputConfig
    decision: DecisionConfig
    futures: FuturesConfig
    news: NewsConfig | None = None

    @property
    def all_symbols(self) -> list[str]:
        return [*self.stable.symbols, *self.volatile.symbols]

    def strategy_for_symbol(self, symbol: str) -> str:
        if symbol in self.stable.symbols:
            return self.stable.strategy
        if symbol in self.volatile.symbols:
            return self.volatile.strategy
        raise ValueError(f"Symbol {symbol!r} not found in any configured universe bucket")


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())

    universe = raw["universe"]
    risk = raw["risk"]
    output = raw["output"]
    date_range = raw["date_range"]
    decision_raw = raw.get("decision") or {}
    futures_raw = raw.get("futures") or {}

    return AppConfig(
        exchange=raw["exchange"],
        timeframe=raw["timeframe"],
        date_range=DateRange(start=date_range["start"], end=date_range["end"]),
        initial_capital=float(raw["initial_capital"]),
        stable=UniverseBucket(
            symbols=list(universe["stable"]["symbols"]),
            strategy=universe["stable"]["strategy"],
        ),
        volatile=UniverseBucket(
            symbols=list(universe["volatile"]["symbols"]),
            strategy=universe["volatile"]["strategy"],
        ),
        strategy_params=dict(raw["strategy_params"]),
        risk=RiskParameters(
            position_size_pct=float(risk["position_size_pct"]),
            stop_loss_pct=float(risk["stop_loss_pct"]),
            take_profit_pct=float(risk["take_profit_pct"]),
            max_concurrent_positions=int(risk["max_concurrent_positions"]),
            fee_pct=float(risk["fee_pct"]),
        ),
        output=OutputConfig(dir=output["dir"], save_csv=bool(output["save_csv"])),
        decision=DecisionConfig(
            news_veto_threshold=float(
                decision_raw.get("news_veto_threshold", DEFAULT_NEWS_VETO_THRESHOLD)
            ),
            live_lookback_candles=int(
                decision_raw.get("live_lookback_candles", DEFAULT_LIVE_LOOKBACK_CANDLES)
            ),
        ),
        futures=FuturesConfig(
            leverage=int(futures_raw.get("leverage", DEFAULT_FUTURES_LEVERAGE)),
            quote_currency=futures_raw.get("quote_currency", DEFAULT_FUTURES_QUOTE_CURRENCY),
        ),
        news=load_news_config(raw.get("news")),
    )
