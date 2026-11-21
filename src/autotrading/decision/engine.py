from __future__ import annotations

from dataclasses import dataclass

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
