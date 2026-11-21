from autotrading.config import load_config

MINIMAL_CONFIG = """
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


def test_decision_defaults_apply_when_section_absent(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_CONFIG)

    config = load_config(path)

    assert config.decision.news_veto_threshold == -0.5
    assert config.decision.live_lookback_candles == 300
    assert config.news is None


def test_decision_overrides_are_respected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        MINIMAL_CONFIG
        + """
decision:
  news_veto_threshold: -0.75
  live_lookback_candles: 500
"""
    )

    config = load_config(path)

    assert config.decision.news_veto_threshold == -0.75
    assert config.decision.live_lookback_candles == 500


def test_default_yaml_loads_end_to_end():
    config = load_config("configs/default.yaml")
    assert config.news is not None
    assert config.decision.news_veto_threshold == -0.5
    assert len(config.all_symbols) > 0
