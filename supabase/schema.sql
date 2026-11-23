-- Run this once by hand in the Supabase SQL editor (Project -> SQL Editor)
-- before the first real run of `autotrading news`, `decide`, `trade`,
-- `scheduled-run`, or `telegram-bot`. Not applied automatically — four
-- tables don't justify a migrations framework for a solo project.

-- Permanent LLM classification cache, shared between the scheduled VPS
-- runs and any local/manual run. A headline is classified via OpenAI
-- exactly once, ever, regardless of how many times
-- `news`/`decide`/`trade`/`scheduled-run` later ask about it.
create table if not exists llm_classification_cache (
    item_id          text primary key,
    label            text not null check (label in ('bullish', 'bearish', 'neutral')),
    confidence       double precision not null,
    relevant_symbols jsonb not null default '[]'::jsonb,
    created_at       timestamptz not null default now()
);

-- Singleton row: runtime-adjustable scheduling + kill switch for
-- `autotrading scheduled-run`, read/written by the scheduled job and
-- (later) a Telegram bot — never by code redeploys. The row self-creates
-- with safe defaults (bot disabled, 60-minute interval) on first use, so
-- no manual INSERT is needed here.
create table if not exists bot_state (
    id                    int primary key default 1,
    bot_enabled           boolean not null default false,
    run_interval_minutes  int not null default 60,
    last_run_at           timestamptz,
    constraint bot_state_singleton check (id = 1)
);

-- `create table if not exists` is a no-op for the already-existing table —
-- explicit ALTERs needed too, same pitfall as closed_trades.closed_via
-- below. NULL means "no override, use the YAML/env-var value" — these are
-- the Telegram-adjustable risk knobs (/settings, /set_leverage, /set_risk).
alter table bot_state add column if not exists leverage int;
alter table bot_state add column if not exists position_size_pct double precision;

-- Closed-trade history — one row per position close, inserted at the
-- orchestration layer (cli.py::run_trade_command, right after a
-- CLOSE_LONG/CLOSE_SHORT order executes) — not inside execution/orders.py,
-- which stays a pure-ccxt module with zero Supabase/secrets knowledge, same
-- reasoning as bot_state living outside execution/. Read by the Telegram
-- bot's /history command.
create table if not exists closed_trades (
    id             bigserial primary key,
    symbol         text not null,
    position_side  text not null check (position_side in ('long', 'short')),
    quantity       double precision not null,
    entry_price    double precision not null,
    exit_price     double precision,
    realized_pnl   double precision,
    closed_at      timestamptz not null default now()
);
create index if not exists closed_trades_closed_at_idx on closed_trades (closed_at desc);

-- `create table if not exists` above is a no-op once the table already
-- exists in production, so new columns need an explicit ALTER — this ran
-- once by hand against the live table in addition to the CREATE above.
alter table closed_trades add column if not exists
    closed_via text not null default 'bot' check (closed_via in ('bot', 'stop_loss'));

-- Tracks positions WE opened (symbol, side, qty, entry) so a scheduled
-- review can notice when Binance shows a symbol as flat that we still
-- think is open — meaning the exchange's own stop-loss (or something
-- external) closed it, not our code. One row per currently-open position
-- we're aware of; deleted once that position is confirmed closed (by us
-- or detected as stop-loss-closed).
create table if not exists open_position_tracking (
    symbol        text primary key,
    position_side text not null check (position_side in ('long', 'short')),
    quantity      double precision not null,
    entry_price   double precision not null,
    opened_at     timestamptz not null default now()
);
