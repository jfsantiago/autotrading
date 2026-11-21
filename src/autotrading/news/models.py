from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SentimentLabel(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class NewsItem:
    """A single news item from any source, before scoring."""

    item_id: str
    source: str
    title: str
    link: str
    published_at: datetime
    native_label: SentimentLabel | None = None
    native_symbols: list[str] | None = None


@dataclass
class LLMClassification:
    label: SentimentLabel
    confidence: float
    relevant_symbols: list[str]


@dataclass
class ScoredItem:
    item: NewsItem
    label: SentimentLabel
    score: float
    symbols: list[str]
    source_weight: float


@dataclass
class SymbolSentiment:
    symbol: str
    average_score: float
    item_count: int


@dataclass
class CryptoEvent:
    date: str
    symbol: str | None
    title: str
    source: str = "coinmarketcal"


@dataclass
class MacroEvent:
    date: str
    type: str
    label: str


@dataclass
class UpcomingEvent:
    date: str
    label: str
    category: str
    symbol: str | None
    is_soon: bool
