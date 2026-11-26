from __future__ import annotations

from typing import Any, Callable

from autotrading.config import AppConfig
from autotrading.execution.client import to_futures_symbol
from autotrading.execution.orders import fetch_realized_pnl
from autotrading.execution.positions import PositionSide
from autotrading.position_tracking import (
    fetch_all_tracked_positions,
    track_open_position,
    untrack_position,
)
from autotrading.secrets import Secrets
from autotrading.trade_history import record_closed_trade

# Takes (secrets, text) — matches telegram_bot.notify's signature. Passed in
# rather than imported directly: this module is used by both cli.py and
# telegram_bot.py, and telegram_bot.py already needs to call this function,
# so importing telegram_bot here would create a circular import.
NotifyFn = Callable[[Secrets, str], None]


def reconcile_external_closes(
    secrets: Secrets,
    futures_client: Any,
    config: AppConfig,
    symbols: list[str],
    positions_by_symbol: dict,
    notify_fn: NotifyFn,
) -> None:
    """Detect positions that closed on Binance's side (its own stop-loss OR
    take-profit order firing, or a manual close outside the bot) without our
    code ever calling close_position — without this, those closes would
    never reach `closed_trades` or notify Telegram. There's no order id to
    tell which resting order actually fired, so the realized PnL sign is
    used as the practical signal: a gain means the take-profit side of the
    bracket was the one that would have closed it (or the position was
    closed favorably some other way), a loss or breakeven is labeled
    stop_loss — matches what actually matters for /history (won or lost),
    even for the manual-close-elsewhere case this can't fully distinguish.
    Also self-heals: tracks any symbol that's live-open but not yet in
    `open_position_tracking` (first run after this feature shipped, or
    tracking that fell out of sync for any reason) using its current live
    entry_price/quantity, so future closes of it can be detected too.

    Called both by the scheduled heartbeat (cli.py) and on-demand from the
    Telegram bot's /positions and /history — so a close doesn't have to
    wait for the next hourly tick to show up, if someone happens to check
    sooner.
    """
    tracked = fetch_all_tracked_positions(secrets)

    for symbol in symbols:
        position = positions_by_symbol[symbol]
        tracked_position = tracked.get(symbol)

        if position.side != PositionSide.FLAT:
            if tracked_position is None:
                track_open_position(
                    secrets, symbol=symbol, position_side=position.side.value,
                    quantity=position.size, entry_price=position.entry_price,
                    margin=position.margin,
                )
            continue

        if tracked_position is None:
            continue  # flat and we already know it — nothing to reconcile

        # We think this symbol is open but Binance shows it flat and we
        # didn't close it ourselves this cycle — cross-check Binance's own
        # income history before concluding a stop-loss fired, so a
        # transient API glitch can't produce a false "closed" record.
        futures_symbol = to_futures_symbol(symbol, config.futures.quote_currency)
        since_ms = int(tracked_position.opened_at.timestamp() * 1000)
        realized_pnl = fetch_realized_pnl(futures_client, futures_symbol, since_ms)
        if realized_pnl is None:
            continue  # leave it tracked, retry on the next cycle

        # No order id to query the actual fill price for an externally
        # triggered close — reconstruct it algebraically from Binance's own
        # realized PnL figure instead: pnl = (exit - entry) * qty for a
        # long, (entry - exit) * qty for a short.
        sign = 1 if tracked_position.position_side == "long" else -1
        exit_price = tracked_position.entry_price + sign * realized_pnl / tracked_position.quantity

        closed_via = "take_profit" if realized_pnl > 0 else "stop_loss"

        try:
            record_closed_trade(
                secrets, symbol=symbol, position_side=tracked_position.position_side,
                quantity=tracked_position.quantity, entry_price=tracked_position.entry_price,
                exit_price=exit_price, realized_pnl=realized_pnl, closed_via=closed_via,
                margin=tracked_position.margin,
            )
            untrack_position(secrets, symbol)
        except Exception as exc:
            print(f"WARNING: failed to record external close for {symbol}: {exc}")
            continue

        label = "TAKE-PROFIT" if closed_via == "take_profit" else "STOP-LOSS"
        notify_fn(secrets, f"{symbol}: cerrado por {label} (automático), PnL {realized_pnl:+.4f}")
