from __future__ import annotations

from autotrading.news.models import SentimentLabel

LABEL_TO_SCORE = {
    SentimentLabel.BULLISH: 1.0,
    SentimentLabel.NEUTRAL: 0.0,
    SentimentLabel.BEARISH: -1.0,
}


def label_to_score(label: SentimentLabel) -> float:
    return LABEL_TO_SCORE[label]
