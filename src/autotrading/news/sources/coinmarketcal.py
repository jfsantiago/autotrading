from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from autotrading.news.cache import get_cached_raw
from autotrading.news.models import CryptoEvent
from autotrading.secrets import Secrets

logger = logging.getLogger(__name__)

COINMARKETCAL_URL = "https://developers.coinmarketcal.com/v1/events"


def _base_symbols(symbols: list[str]) -> list[str]:
    seen: list[str] = []
    for symbol in symbols:
        base = symbol.split("/")[0]
        if base not in seen:
            seen.append(base)
    return seen


def fetch_crypto_events(
    secrets: Secrets,
    symbols: list[str],
    lookahead_days: int,
    cache_dir: Path,
    ttl_hours: float,
) -> list[CryptoEvent]:
    """Fetch upcoming crypto events (listings, unlocks, etc.) from CoinMarketCal.

    CoinMarketCal's free tier is modest (confirm current limits at
    coinmarketcal.com/developer/docs before relying on this in production —
    free-tier terms shift, as CryptoPanic's did). Degrades to [] on any
    missing key or request failure rather than crashing the news run.
    """
    if not secrets.coinmarketcal_api_key:
        logger.warning("COINMARKETCAL_API_KEY not set, skipping crypto events source")
        return []

    coins = _base_symbols(symbols)
    if not coins:
        return []

    cache_key = f"coinmarketcal:{','.join(coins)}:{lookahead_days}"

    def _fetch() -> dict:
        today = datetime.now(timezone.utc).date()
        response = requests.get(
            COINMARKETCAL_URL,
            headers={"x-api-key": secrets.coinmarketcal_api_key, "Accept": "application/json"},
            params={
                "coins": ",".join(c.lower() for c in coins),
                "dateRangeStart": today.isoformat(),
                "dateRangeEnd": (today + timedelta(days=lookahead_days)).isoformat(),
                "max": 100,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = get_cached_raw(cache_dir, cache_key, ttl_hours, _fetch)
    except Exception:
        logger.exception("CoinMarketCal fetch failed, degrading to no crypto events")
        return []

    events: list[CryptoEvent] = []
    for raw_event in payload.get("body", []):
        date_event = raw_event.get("date_event")
        title = (raw_event.get("title") or {}).get("en") or raw_event.get("displayed_date")
        if not date_event or not title:
            continue

        coin_symbol = None
        coin_info = raw_event.get("coins") or []
        if coin_info:
            coin_symbol = (coin_info[0].get("symbol") or "").upper() or None

        events.append(
            CryptoEvent(date=date_event[:10], symbol=coin_symbol, title=title)
        )
    return events
