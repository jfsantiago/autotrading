from types import SimpleNamespace
from unittest.mock import patch

from autotrading.cli import build_arg_parser, main
from autotrading.decision.engine import Decision
from autotrading.news.pipeline import NewsSnapshot
from autotrading.secrets import Secrets
from autotrading.strategies.base import Signal


def test_decide_subcommand_parses_args():
    parser = build_arg_parser()
    args = parser.parse_args(["decide", "--config", "configs/default.yaml"])
    assert args.command == "decide"
    assert args.config == "configs/default.yaml"


def test_decide_command_dry_run_no_network(tmp_path, capsys):
    fake_config = SimpleNamespace(
        news=SimpleNamespace(output=SimpleNamespace(dir="x", save_csv=False)),
        all_symbols=["BTC/USDT"],
        decision=SimpleNamespace(news_veto_threshold=-0.5, live_lookback_candles=300),
        timeframe="1h",
        strategy_for_symbol=lambda s: "stable_trend",
        strategy_params={"stable_trend": {}},
    )
    fake_secrets = Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
    )
    fake_snapshot = NewsSnapshot(scored_items=[], symbol_sentiments={}, upcoming_events=[])

    with (
        patch("autotrading.cli.load_config", return_value=fake_config),
        patch("autotrading.cli.load_secrets", return_value=fake_secrets),
        patch("autotrading.cli.build_news_snapshot", return_value=fake_snapshot),
        patch("autotrading.cli.make_public_client", return_value=object()),
        patch("autotrading.cli.get_latest_signal", return_value=(Signal.HOLD, None)),
    ):
        exit_code = main(["decide", "--config", "fake.yaml", "--output", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "No orders were placed" in out or "no orders were placed" in out.lower()
    assert (tmp_path / "decisions.csv").exists()


def test_decide_command_errors_without_news_config():
    fake_config = SimpleNamespace(news=None)

    with patch("autotrading.cli.load_config", return_value=fake_config):
        exit_code = main(["decide", "--config", "fake.yaml"])

    assert exit_code == 1
