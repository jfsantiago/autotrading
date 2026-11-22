from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Secrets:
    openai_api_key: str
    newsdata_api_key: str | None
    coinmarketcal_api_key: str | None
    binance_demo_api_key: str | None = None
    binance_demo_api_secret: str | None = None


def load_secrets() -> Secrets:
    """Load secrets from the environment (via a .env file if present).

    Only OPENAI_API_KEY is required — without it there is no way to
    classify headlines. The others degrade their respective sources to
    disabled rather than failing the whole run.
    """
    load_dotenv()

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    return Secrets(
        openai_api_key=openai_api_key,
        newsdata_api_key=os.environ.get("NEWSDATA_API_KEY") or None,
        coinmarketcal_api_key=os.environ.get("COINMARKETCAL_API_KEY") or None,
        binance_demo_api_key=os.environ.get("BINANCE_DEMO_API_KEY") or None,
        binance_demo_api_secret=os.environ.get("BINANCE_DEMO_API_SECRET") or None,
    )
