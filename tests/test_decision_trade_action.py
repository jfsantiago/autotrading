from autotrading.decision.engine import OrderAction, decide_trade_action
from autotrading.execution.positions import PositionSide, PositionState
from autotrading.news.models import SymbolSentiment
from autotrading.strategies.base import Signal

VETO_THRESHOLD = -0.5


def make_position(side):
    return PositionState(symbol="BTC/USDT", side=side, size=1.0 if side != PositionSide.FLAT else 0.0, entry_price=100.0)


def make_sentiment(score):
    return SymbolSentiment(symbol="BTC/USDT", average_score=score, item_count=3)


def test_buy_flat_opens_long_no_news():
    result = decide_trade_action("BTC/USDT", Signal.BUY, make_position(PositionSide.FLAT), None, VETO_THRESHOLD)
    assert result.order_action == OrderAction.OPEN_LONG


def test_buy_flat_vetoed_by_bearish_news():
    result = decide_trade_action(
        "BTC/USDT", Signal.BUY, make_position(PositionSide.FLAT), make_sentiment(-0.8), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.NONE


def test_buy_flat_confirmed_by_mild_news():
    result = decide_trade_action(
        "BTC/USDT", Signal.BUY, make_position(PositionSide.FLAT), make_sentiment(-0.2), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.OPEN_LONG


def test_buy_while_long_is_noop():
    result = decide_trade_action("BTC/USDT", Signal.BUY, make_position(PositionSide.LONG), None, VETO_THRESHOLD)
    assert result.order_action == OrderAction.NONE


def test_buy_while_short_closes_short_even_with_bearish_news():
    result = decide_trade_action(
        "BTC/USDT", Signal.BUY, make_position(PositionSide.SHORT), make_sentiment(-0.9), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.CLOSE_SHORT


def test_sell_flat_opens_short_no_news():
    result = decide_trade_action("BTC/USDT", Signal.SELL, make_position(PositionSide.FLAT), None, VETO_THRESHOLD)
    assert result.order_action == OrderAction.OPEN_SHORT


def test_sell_flat_vetoed_by_bullish_news_symmetric():
    result = decide_trade_action(
        "BTC/USDT", Signal.SELL, make_position(PositionSide.FLAT), make_sentiment(0.8), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.NONE


def test_sell_flat_confirmed_by_mild_news():
    result = decide_trade_action(
        "BTC/USDT", Signal.SELL, make_position(PositionSide.FLAT), make_sentiment(0.2), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.OPEN_SHORT


def test_sell_while_short_is_noop():
    result = decide_trade_action("BTC/USDT", Signal.SELL, make_position(PositionSide.SHORT), None, VETO_THRESHOLD)
    assert result.order_action == OrderAction.NONE


def test_sell_while_long_closes_long_even_with_bullish_news():
    result = decide_trade_action(
        "BTC/USDT", Signal.SELL, make_position(PositionSide.LONG), make_sentiment(0.9), VETO_THRESHOLD
    )
    assert result.order_action == OrderAction.CLOSE_LONG


def test_hold_is_always_noop():
    for side in PositionSide:
        result = decide_trade_action("BTC/USDT", Signal.HOLD, make_position(side), make_sentiment(-0.9), VETO_THRESHOLD)
        assert result.order_action == OrderAction.NONE
