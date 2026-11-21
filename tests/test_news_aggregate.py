from datetime import datetime, timezone

from autotrading.news.aggregate import aggregate_by_symbol
from autotrading.news.models import NewsItem, ScoredItem, SentimentLabel


def make_scored(symbols, score, source_weight=1.0):
    item = NewsItem(
        item_id="x",
        source="test",
        title="t",
        link="http://x",
        published_at=datetime.now(timezone.utc),
    )
    return ScoredItem(
        item=item, label=SentimentLabel.NEUTRAL, score=score, symbols=symbols, source_weight=source_weight
    )


def test_aggregate_simple_average():
    all_symbols = ["BTC/USDT", "ETH/USDT"]
    items = [
        make_scored(["BTC"], 1.0),
        make_scored(["BTC"], -0.5),
        make_scored(["ETH"], 0.5),
    ]
    result = aggregate_by_symbol(items, all_symbols)

    assert result["BTC/USDT"].item_count == 2
    assert result["BTC/USDT"].average_score == 0.25
    assert result["ETH/USDT"].item_count == 1
    assert result["ETH/USDT"].average_score == 0.5


def test_aggregate_ignores_symbols_outside_universe():
    all_symbols = ["BTC/USDT"]
    items = [make_scored(["DOGE"], 1.0)]
    result = aggregate_by_symbol(items, all_symbols)
    assert result == {}


def test_aggregate_weighted_by_source_weight():
    all_symbols = ["BTC/USDT"]
    items = [
        make_scored(["BTC"], 1.0, source_weight=2.0),
        make_scored(["BTC"], -1.0, source_weight=1.0),
    ]
    result = aggregate_by_symbol(items, all_symbols)
    # (1.0*2 + -1.0*1) / (2+1) = 1/3
    assert round(result["BTC/USDT"].average_score, 4) == round(1 / 3, 4)
