from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from autotrading.execution.positions import PositionSide, PositionState
from autotrading.news.models import SymbolSentiment
from autotrading.strategies.base import Signal


@dataclass
class Decision:
    symbol: str
    technical_signal: Signal
    news_score: float | None  # the score actually used in the veto check; None if not applicable
    action: Signal
    reason: str


def decide(
    symbol: str,
    technical_signal: Signal,
    news_sentiment: SymbolSentiment | None,
    veto_threshold: float,
) -> Decision:
    """Combine a technical signal with news sentiment via a veto filter.

    The technical signal is authoritative. News sentiment can only block a
    BUY when it's meaningfully negative (score < veto_threshold) — it never
    creates a BUY on its own, and never affects SELL/HOLD. No news coverage
    for the symbol means no veto (absence of news shouldn't block a trade).
    """
    if technical_signal == Signal.SELL:
        return Decision(
            symbol,
            technical_signal,
            None,
            Signal.SELL,
            "SELL — news sentiment not considered for sell/hold signals",
        )
    if technical_signal == Signal.HOLD:
        return Decision(
            symbol,
            technical_signal,
            None,
            Signal.HOLD,
            "technical signal is HOLD, no news check needed",
        )

    # technical_signal == Signal.BUY
    if news_sentiment is None:
        return Decision(symbol, Signal.BUY, None, Signal.BUY, "BUY confirmed: no news coverage")

    score = news_sentiment.average_score
    if score < veto_threshold:
        return Decision(
            symbol,
            Signal.BUY,
            score,
            Signal.HOLD,
            f"BUY vetoed: news sentiment {score:+.2f} below threshold {veto_threshold:+.2f}",
        )
    return Decision(
        symbol,
        Signal.BUY,
        score,
        Signal.BUY,
        f"BUY confirmed: news sentiment {score:+.2f} at/above threshold {veto_threshold:+.2f}",
    )


class OrderAction(str, Enum):
    NONE = "none"
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


@dataclass
class TradeDecision:
    symbol: str
    technical_signal: Signal
    position_side: PositionSide
    news_score: float | None
    order_action: OrderAction
    reason: str


def decide_trade_action(
    symbol: str,
    technical_signal: Signal,
    position: PositionState,
    news_sentiment: SymbolSentiment | None,
    veto_threshold: float,
) -> TradeDecision:
    """Direction-aware decision for futures trading: combines the technical
    signal with the ACTUAL current position (never assumed — always fetched
    from the exchange) and a symmetric news veto.

    - BUY while flat -> open long, unless news is meaningfully bearish.
    - SELL while flat -> open short, unless news is meaningfully bullish
      (symmetric to the long-side veto).
    - A signal that opposes the current position closes it (never flips in
      one order) — the next run re-evaluates opening the other side from a
      freshly-fetched flat state.
    - A signal that matches the current position, or HOLD, is a no-op.
    - Closing is never vetoed by news — reducing risk shouldn't be blocked.
    """
    score = news_sentiment.average_score if news_sentiment is not None else None

    if technical_signal == Signal.HOLD:
        return TradeDecision(
            symbol, technical_signal, position.side, None, OrderAction.NONE,
            "technical signal is HOLD, no action",
        )

    if technical_signal == Signal.BUY:
        if position.side == PositionSide.LONG:
            return TradeDecision(
                symbol, technical_signal, position.side, None, OrderAction.NONE,
                "already long, no action",
            )
        if position.side == PositionSide.SHORT:
            return TradeDecision(
                symbol, technical_signal, position.side, None, OrderAction.CLOSE_SHORT,
                "BUY while short: closing short (never vetoed by news)",
            )
        # FLAT
        if score is not None and score < veto_threshold:
            return TradeDecision(
                symbol, technical_signal, position.side, score, OrderAction.NONE,
                f"open long vetoed: news sentiment {score:+.2f} below threshold {veto_threshold:+.2f}",
            )
        return TradeDecision(
            symbol, technical_signal, position.side, score, OrderAction.OPEN_LONG,
            "open long confirmed" if score is None else f"open long confirmed: news sentiment {score:+.2f}",
        )

    # technical_signal == Signal.SELL
    if position.side == PositionSide.SHORT:
        return TradeDecision(
            symbol, technical_signal, position.side, None, OrderAction.NONE,
            "already short, no action",
        )
    if position.side == PositionSide.LONG:
        return TradeDecision(
            symbol, technical_signal, position.side, None, OrderAction.CLOSE_LONG,
            "SELL while long: closing long (never vetoed by news)",
        )
    # FLAT — symmetric veto: very bullish news blocks opening a short
    symmetric_threshold = -veto_threshold
    if score is not None and score > symmetric_threshold:
        return TradeDecision(
            symbol, technical_signal, position.side, score, OrderAction.NONE,
            f"open short vetoed: news sentiment {score:+.2f} above threshold {symmetric_threshold:+.2f}",
        )
    return TradeDecision(
        symbol, technical_signal, position.side, score, OrderAction.OPEN_SHORT,
        "open short confirmed" if score is None else f"open short confirmed: news sentiment {score:+.2f}",
    )
