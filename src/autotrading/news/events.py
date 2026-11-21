from __future__ import annotations

from datetime import date, datetime, timezone

from autotrading.news.models import CryptoEvent, MacroEvent, UpcomingEvent


def _parse_date(date_str: str) -> date:
    return datetime.strptime(date_str[:10], "%Y-%m-%d").date()


def merge_events(
    crypto_events: list[CryptoEvent],
    macro_events: list[MacroEvent],
    soon_threshold_days: int,
    today: date | None = None,
) -> list[UpcomingEvent]:
    """Merge crypto + macro events into one sorted, future-only upcoming-events view."""
    today = today or datetime.now(timezone.utc).date()

    upcoming: list[UpcomingEvent] = []

    for event in macro_events:
        event_date = _parse_date(event.date)
        if event_date < today:
            continue
        upcoming.append(
            UpcomingEvent(
                date=event.date,
                label=event.label,
                category=event.type,
                symbol=None,
                is_soon=(event_date - today).days <= soon_threshold_days,
            )
        )

    for event in crypto_events:
        event_date = _parse_date(event.date)
        if event_date < today:
            continue
        upcoming.append(
            UpcomingEvent(
                date=event.date,
                label=event.title,
                category="crypto_event",
                symbol=event.symbol,
                is_soon=(event_date - today).days <= soon_threshold_days,
            )
        )

    return sorted(upcoming, key=lambda e: e.date)
