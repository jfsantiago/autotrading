from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from autotrading.news.config import NewsConfig, load_news_config

# Env vars that override the matching YAML value, for runtime tuning without
# editing/redeploying the config file — the intended on-ramp for a future
# Telegram-driven control bot. Checked at load time, not polled continuously.
ENV_POSITION_SIZE_PCT = "AUTOTRADING_POSITION_SIZE_PCT"
ENV_LEVERAGE = "AUTOTRADING_LEVERAGE"

# Hard ceiling on risk-per-trade, independent of YAML or env var overrides —
# same defense-in-depth spirit as execution/client.py's MAX_LEVERAGE_CEILING.
# Exposing position_size_pct to env-var (and later Telegram) control makes
# this more important, not less: an external control surface could someday
# set something unsafe, and this is the last line of defense in code.
MAX_POSITION_SIZE_PCT_CEILING = 0.25

# take_profit_margin_pct / stop_loss_margin_pct are expressed as a fraction
# of the MARGIN actually at risk (real money), not of price movement — see
# RiskParameters below. Kept at a fixed 2:1 ratio rather than two
# independently adjustable knobs, so a Telegram-driven change can never
# accidentally flip the risk/reward ratio against the trader (confirmed via
# backtest that both strategies sit right at the ~33% breakeven win rate for
# a 1:2 ratio — inverting it would need a win rate neither comes close to).
TAKE_PROFIT_TO_STOP_LOSS_RATIO = 2
MAX_TAKE_PROFIT_MARGIN_PCT_CEILING = 1.0


def _env_override(name: str, yaml_value: Any) -> Any:
    # `or None` also treats an empty string as absent — python-dotenv sets
    # the var to "" (not unset) for a blank "KEY=" line in .env.
    value = os.environ.get(name) or None
    return value if value is not None else yaml_value


def assert_position_size_safe(
    position_size_pct: float, ceiling: float = MAX_POSITION_SIZE_PCT_CEILING
) -> None:
    if position_size_pct <= 0 or position_size_pct > ceiling:
        raise ValueError(
            f"position_size_pct {position_size_pct} is outside the allowed range "
            f"(0, {ceiling}]. This ceiling is hardcoded as a safety invariant, "
            "not configurable."
        )


def assert_take_profit_margin_safe(
    take_profit_margin_pct: float, ceiling: float = MAX_TAKE_PROFIT_MARGIN_PCT_CEILING
) -> None:
    if take_profit_margin_pct <= 0 or take_profit_margin_pct > ceiling:
        raise ValueError(
            f"take_profit_margin_pct {take_profit_margin_pct} is outside the allowed "
            f"range (0, {ceiling}]. This ceiling is hardcoded as a safety invariant, "
            "not configurable."
        )


@dataclass
class RiskParameters:
    """Risk parameters for position sizing and exits.

    take_profit_margin_pct/stop_loss_margin_pct are fractions of the real
    USDT margin at risk (pre-leverage capital), not of price movement —
    the actual price distance needed is this divided by the leverage used,
    computed where the order is placed (execution/orders.py) or simulated
    (engine/risk.py). This way the real money at risk per trade stays
    constant no matter what leverage is chosen, instead of silently
    scaling with it as a price-based percentage would.
    """

    position_size_pct: float
    take_profit_margin_pct: float
    max_concurrent_positions: int
    fee_pct: float

    @property
    def stop_loss_margin_pct(self) -> float:
        return self.take_profit_margin_pct / TAKE_PROFIT_TO_STOP_LOSS_RATIO


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
    load_dotenv()  # allow env var overrides below, whether set via shell or .env
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
            position_size_pct=float(
                _env_override(ENV_POSITION_SIZE_PCT, risk["position_size_pct"])
            ),
            take_profit_margin_pct=float(risk["take_profit_margin_pct"]),
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
            leverage=int(
                _env_override(
                    ENV_LEVERAGE, futures_raw.get("leverage", DEFAULT_FUTURES_LEVERAGE)
                )
            ),
            quote_currency=futures_raw.get("quote_currency", DEFAULT_FUTURES_QUOTE_CURRENCY),
        ),
        news=load_news_config(raw.get("news")),
    )
