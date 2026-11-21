from __future__ import annotations

from datetime import datetime, timezone

TIMEFRAME_TO_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def parse_date_to_ms(date_str: str) -> int:
    """Parse a 'YYYY-MM-DD' string into a UTC millisecond timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def timeframe_to_ms(timeframe: str) -> int:
    if timeframe not in TIMEFRAME_TO_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe!r}")
    return TIMEFRAME_TO_MS[timeframe]
