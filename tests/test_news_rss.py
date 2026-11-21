from pathlib import Path

from autotrading.news.sources.rss import fetch_one_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_fetch_one_feed_parses_items_from_local_fixture():
    items = fetch_one_feed(str(FIXTURE), limit=10)

    assert len(items) == 2
    assert items[0].title == "Bitcoin rallies past key resistance"
    assert items[0].link == "http://example.com/btc-rally"
    assert items[0].source == "Sample Crypto News"
    assert items[0].item_id != items[1].item_id


def test_fetch_one_feed_respects_limit():
    items = fetch_one_feed(str(FIXTURE), limit=1)
    assert len(items) == 1
