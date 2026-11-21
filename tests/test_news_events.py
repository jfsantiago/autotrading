from datetime import date

from autotrading.news.events import merge_events
from autotrading.news.models import CryptoEvent, MacroEvent


def test_merge_events_filters_past_and_sorts():
    today = date(2026, 1, 1)
    macro = [
        MacroEvent(date="2025-12-31", type="cpi", label="past, excluded"),
        MacroEvent(date="2026-01-10", type="fomc", label="fomc meeting"),
    ]
    crypto = [CryptoEvent(date="2026-01-02", symbol="BTC", title="unlock")]

    result = merge_events(crypto, macro, soon_threshold_days=3, today=today)

    assert [e.label for e in result] == ["unlock", "fomc meeting"]
    assert result[0].is_soon is True
    assert result[1].is_soon is False


def test_merge_events_includes_today():
    today = date(2026, 1, 1)
    macro = [MacroEvent(date="2026-01-01", type="cpi", label="today")]

    result = merge_events([], macro, soon_threshold_days=0, today=today)

    assert len(result) == 1
    assert result[0].is_soon is True
