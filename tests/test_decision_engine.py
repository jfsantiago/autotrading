from autotrading.decision.engine import decide
from autotrading.news.models import SymbolSentiment
from autotrading.strategies.base import Signal


def make_sentiment(score, item_count=3):
    return SymbolSentiment(symbol="BTC/USDT", average_score=score, item_count=item_count)


def test_buy_confirmed_when_no_news_coverage():
    result = decide("BTC/USDT", Signal.BUY, None, veto_threshold=-0.5)
    assert result.action == Signal.BUY
    assert result.news_score is None
    assert "no news coverage" in result.reason


def test_buy_confirmed_when_sentiment_above_threshold():
    result = decide("BTC/USDT", Signal.BUY, make_sentiment(-0.2), veto_threshold=-0.5)
    assert result.action == Signal.BUY
    assert result.news_score == -0.2


def test_buy_vetoed_when_sentiment_below_threshold():
    result = decide("BTC/USDT", Signal.BUY, make_sentiment(-0.8), veto_threshold=-0.5)
    assert result.action == Signal.HOLD
    assert result.technical_signal == Signal.BUY
    assert result.news_score == -0.8
    assert "vetoed" in result.reason


def test_buy_not_vetoed_when_sentiment_exactly_at_threshold():
    result = decide("BTC/USDT", Signal.BUY, make_sentiment(-0.5), veto_threshold=-0.5)
    assert result.action == Signal.BUY


def test_sell_passes_through_ignoring_sentiment():
    result = decide("BTC/USDT", Signal.SELL, make_sentiment(-1.0), veto_threshold=-0.5)
    assert result.action == Signal.SELL
    assert result.news_score is None


def test_hold_passes_through_ignoring_sentiment():
    result = decide("BTC/USDT", Signal.HOLD, make_sentiment(-1.0), veto_threshold=-0.5)
    assert result.action == Signal.HOLD
    assert result.news_score is None


def test_symbol_is_carried_through():
    result = decide("ETH/USDT", Signal.BUY, None, veto_threshold=-0.5)
    assert result.symbol == "ETH/USDT"
