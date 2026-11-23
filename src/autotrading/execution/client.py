from __future__ import annotations

import re

import ccxt

from autotrading.secrets import Secrets

MAX_LEVERAGE_CEILING = 10  # hard ceiling in code, independent of whatever the YAML says

# Binance quotes futures contracts for a handful of extremely low-priced
# tokens in units of 1000 (to avoid excessive decimal precision) - the
# futures base ticker differs from the spot one. Confirmed live: spot
# "PEPE/USDT" has no "PEPE/USDT:USDT" futures market, only
# "1000PEPE/USDT:USDT". Add entries here if the universe ever includes
# another such token (e.g. 1000SHIB, 1000BONK, 1000FLOKI have existed).
# Deliberately NOT used by news/sources (NewsData.io, CoinMarketCal) — those
# need the real spot ticker to match real-world coin databases.
FUTURES_BASE_SYMBOL_OVERRIDES = {
    "PEPE": "1000PEPE",
}


def to_futures_symbol(symbol: str, quote_currency: str = "USDT") -> str:
    """'BTC/USDT' -> 'BTC/USDT:USDT' (ccxt's unified symbol for a USDT-margined
    linear perpetual swap). Only USDT-margined perps are supported this phase.
    """
    suffix = f"/{quote_currency}"
    if not symbol.endswith(suffix):
        raise ValueError(
            f"Symbol {symbol!r} does not end in {suffix!r}; only {quote_currency}-margined "
            "linear perpetuals are supported."
        )
    base = symbol[: -len(suffix)]
    base = FUTURES_BASE_SYMBOL_OVERRIDES.get(base, base)
    return f"{base}/{quote_currency}:{quote_currency}"


def futures_contract_multiplier(symbol: str, quote_currency: str = "USDT") -> int:
    """A quantity computed from the real per-token spot price (as
    calculate_position_size does) is in actual token units. For a "1000X"
    contract (see FUTURES_BASE_SYMBOL_OVERRIDES), Binance's order quantity
    is denominated in batches of that many tokens, not individual tokens —
    sending the raw token count as-is overshoots the exchange's max order
    quantity by the same factor. Confirmed live: an order for PEPE failed
    with -4005 "Quantity greater than max quantity" before this existed.
    The multiplier is parsed from the override's "1000PEPE"-style prefix
    rather than hardcoded, so it keeps working if more such entries are
    added (1000SHIB, 1000BONK, etc. all follow the same naming).
    """
    suffix = f"/{quote_currency}"
    base = symbol[: -len(suffix)] if symbol.endswith(suffix) else symbol
    futures_base = FUTURES_BASE_SYMBOL_OVERRIDES.get(base)
    if futures_base is None:
        return 1
    match = re.match(r"(\d+)", futures_base)
    return int(match.group(1)) if match else 1


def assert_leverage_safe(leverage: int, ceiling: int = MAX_LEVERAGE_CEILING) -> None:
    if leverage < 1 or leverage > ceiling:
        raise ValueError(
            f"Leverage {leverage}x is outside the allowed range [1, {ceiling}]x. "
            "This ceiling is hardcoded as a safety invariant, not configurable."
        )


def require_execution_secrets(secrets: Secrets) -> None:
    if not secrets.binance_demo_api_key or not secrets.binance_demo_api_secret:
        raise RuntimeError(
            "BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET are not set. "
            "Binance retired the old Futures Testnet — get new keys from "
            "https://demo.binance.com/en/my/settings/api-management "
            "(old testnet.binancefuture.com keys will NOT work) and add them to .env."
        )


def make_futures_demo_client(secrets: Secrets) -> ccxt.binance:
    """Client for Binance's Demo Trading environment (demo.binance.com),
    which replaced the old Futures Testnet. ccxt's set_sandbox_mode() no
    longer works for futures private endpoints — enable_demo_trading() is
    the current mechanism (and is mutually exclusive with sandbox mode).
    """
    require_execution_secrets(secrets)
    client = ccxt.binance(
        {
            "apiKey": secrets.binance_demo_api_key,
            "secret": secrets.binance_demo_api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
    )
    client.enable_demo_trading(True)
    client.load_markets()  # ensures amount_to_precision/price_to_precision work downstream
    return client
