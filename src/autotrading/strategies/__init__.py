from __future__ import annotations

from autotrading.strategies.base import Signal, Strategy
from autotrading.strategies.stable_trend import StableTrendStrategy
from autotrading.strategies.volatile_breakout import VolatileBreakoutStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "stable_trend": StableTrendStrategy,
    "volatile_breakout": VolatileBreakoutStrategy,
}

__all__ = ["Signal", "Strategy", "STRATEGY_REGISTRY"]
