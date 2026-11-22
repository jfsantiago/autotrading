-- Run this once by hand in the Supabase SQL editor (Project -> SQL Editor)
-- before the first real run of `autotrading news`, `decide`, `trade`, or
-- `scheduled-run`. Not applied automatically — two tables don't justify a
-- migrations framework for a solo project.

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
