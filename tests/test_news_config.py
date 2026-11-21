from autotrading.config import load_config
from autotrading.news.config import load_news_config


def test_load_news_config_none_when_absent():
    assert load_news_config(None) is None


def test_load_news_config_parses_sections():
    raw = {
        "rss": {"feeds": ["http://a"], "fetch_limit_per_feed": 10},
        "newsdata": {"enabled": True, "source_weight": 0.5},
        "sentiment": {"llm_model": "m", "llm_batch_size": 5, "llm_source_weight": 1.0},
        "calendar": {
            "crypto_events_enabled": False,
            "lookahead_days": 7,
            "macro_events_file": "x.yaml",
            "soon_threshold_days": 2,
        },
        "cache": {"dir": "d", "raw_ttl_hours": 3},
        "output": {"dir": "o", "save_csv": False},
    }
    cfg = load_news_config(raw)
    assert cfg.rss.feeds == ["http://a"]
    assert cfg.newsdata.enabled is True
    assert cfg.sentiment.llm_batch_size == 5
    assert cfg.calendar.lookahead_days == 7
    assert cfg.cache.raw_ttl_hours == 3
    assert cfg.output.save_csv is False


def test_app_config_without_news_section_stays_none(tmp_path):
    config_path = tmp_path / "no_news.yaml"
    config_path.write_text(
        """
exchange: binance
timeframe: "1h"
date_range:
  start: "2024-01-01"
  end: "2024-02-01"
initial_capital: 1000
universe:
  stable:
    symbols: ["BTC/USDT"]
    strategy: stable_trend
  volatile:
    symbols: []
    strategy: volatile_breakout
strategy_params:
  stable_trend: {fast_ma: 5, slow_ma: 10, rsi_period: 14, rsi_buy_max: 70, rsi_sell_min: 30}
  volatile_breakout: {pct_change_window: 5, pct_change_threshold: 0.05, volume_window: 20, volume_spike_zscore: 2.0}
risk:
  position_size_pct: 0.04
  stop_loss_pct: 0.03
  take_profit_pct: 0.06
  max_concurrent_positions: 5
  fee_pct: 0.001
output:
  dir: "results"
  save_csv: true
"""
    )
    config = load_config(config_path)
    assert config.news is None
