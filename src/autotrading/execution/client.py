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
    return client
