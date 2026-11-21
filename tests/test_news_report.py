from datetime import datetime, timezone

from autotrading.news.models import NewsItem, ScoredItem, SentimentLabel, SymbolSentiment, UpcomingEvent
from autotrading.news.report import print_news_summary, save_news_results


def make_scored_item():
    item = NewsItem(
        item_id="1",
        source="test",
        title="headline",
        link="http://x",
        published_at=datetime.now(timezone.utc),
    )
    return ScoredItem(
        item=item, label=SentimentLabel.BULLISH, score=1.0, symbols=["BTC"], source_weight=1.0
    )


def test_print_news_summary_handles_empty(capsys):
    print_news_summary({}, [])
    out = capsys.readouterr().out
    assert "No scored news items" in out
    assert "No upcoming events" in out


def test_save_news_results_writes_csvs(tmp_path):
    scored = [make_scored_item()]
    sentiments = {"BTC/USDT": SymbolSentiment(symbol="BTC/USDT", average_score=1.0, item_count=1)}
    events = [
        UpcomingEvent(
            date="2026-01-01", label="fomc", category="fomc", symbol=None, is_soon=True
        )
    ]

    save_news_results(scored, sentiments, events, tmp_path)

    assert (tmp_path / "news_items.csv").exists()
    assert (tmp_path / "symbol_sentiment.csv").exists()
    assert (tmp_path / "upcoming_events.csv").exists()
