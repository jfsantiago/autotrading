from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Secrets:
    anthropic_api_key: str
    newsdata_api_key: str | None
    coinmarketcal_api_key: str | None


def load_secrets() -> Secrets:
    """Load secrets from the environment (via a .env file if present).

    Only ANTHROPIC_API_KEY is required — without it there is no way to
    classify headlines. The others degrade their respective sources to
    disabled rather than failing the whole run.
    """
    load_dotenv()

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    return Secrets(
        anthropic_api_key=anthropic_api_key,
        newsdata_api_key=os.environ.get("NEWSDATA_API_KEY") or None,
        coinmarketcal_api_key=os.environ.get("COINMARKETCAL_API_KEY") or None,
    )
