from __future__ import annotations

import ccxt

from autotrading.secrets import Secrets

MAX_LEVERAGE_CEILING = 10  # hard ceiling in code, independent of whatever the YAML says


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
    return f"{symbol}:{quote_currency}"


def assert_leverage_safe(leverage: int, ceiling: int = MAX_LEVERAGE_CEILING) -> None:
    if leverage < 1 or leverage > ceiling:
        raise ValueError(
            f"Leverage {leverage}x is outside the allowed range [1, {ceiling}]x. "
            "This ceiling is hardcoded as a safety invariant, not configurable."
        )


def require_execution_secrets(secrets: Secrets) -> None:
    if not secrets.binance_testnet_api_key or not secrets.binance_testnet_api_secret:
        raise RuntimeError(
            "BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET are not set. "
            "Get them from https://testnet.binancefuture.com/ (a separate signup, "
            "not your real Binance account) and add them to .env."
        )


def make_futures_testnet_client(secrets: Secrets) -> ccxt.binance:
    require_execution_secrets(secrets)
    client = ccxt.binance(
        {
            "apiKey": secrets.binance_testnet_api_key,
            "secret": secrets.binance_testnet_api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
    )
    client.set_sandbox_mode(True)
    return client
