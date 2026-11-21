from autotrading.news.models import SentimentLabel
from autotrading.news.scoring import label_to_score


def test_label_to_score_mapping():
    assert label_to_score(SentimentLabel.BULLISH) == 1.0
    assert label_to_score(SentimentLabel.NEUTRAL) == 0.0
    assert label_to_score(SentimentLabel.BEARISH) == -1.0
