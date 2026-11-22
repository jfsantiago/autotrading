from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from autotrading.cli import main
from autotrading.execution.orders import OrderResult
from autotrading.execution.positions import PositionSide, PositionState
from autotrading.news.pipeline import NewsSnapshot
from autotrading.secrets import Secrets
from autotrading.strategies.base import Signal


def make_fake_config():
    return SimpleNamespace(
        news=SimpleNamespace(output=SimpleNamespace(dir="x", save_csv=False)),
        all_symbols=["BTC/USDT"],
        decision=SimpleNamespace(news_veto_threshold=-0.5, live_lookback_candles=300),
        futures=SimpleNamespace(leverage=4, quote_currency="USDT"),
        risk=SimpleNamespace(position_size_pct=0.04, stop_loss_pct=0.03),
        timeframe="1h",
        strategy_for_symbol=lambda s: "stable_trend",
        strategy_params={"stable_trend": {}},
    )


def make_fake_secrets():
    return Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
        binance_demo_api_key="tk",
        binance_demo_api_secret="ts",
    )


def common_patches(tmp_path, flat_position=True):
    df = pd.DataFrame({"close": [100.0]})
    position = PositionState(
        symbol="BTC/USDT",
        side=PositionSide.FLAT if flat_position else PositionSide.LONG,
        size=0.0 if flat_position else 1.0,
        entry_price=None if flat_position else 100.0,
    )
    return [
        patch("autotrading.cli.load_config", return_value=make_fake_config()),
        patch("autotrading.cli.load_secrets", return_value=make_fake_secrets()),
        patch(
            "autotrading.cli.build_news_snapshot",
            return_value=NewsSnapshot(scored_items=[], symbol_sentiments={}, upcoming_events=[]),
        ),
        patch("autotrading.cli.make_public_client", return_value=object()),
        patch("autotrading.cli.make_futures_demo_client", return_value=object()),
        patch("autotrading.cli.get_latest_signal", return_value=(Signal.BUY, df)),
        patch("autotrading.cli.get_position_state", return_value=position),
    ]


def test_trade_without_confirm_never_places_orders(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with patch("autotrading.cli.open_long") as mock_open_long:
            exit_code = main(["trade", "--config", "fake.yaml", "--output", str(tmp_path)])
            mock_open_long.assert_not_called()

    assert exit_code == 0
    assert (tmp_path / "trades.csv").exists()


def test_trade_with_confirm_opens_long(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    fake_result = OrderResult(
        symbol="BTC/USDT", action="open_long", entry_order={"id": "1"}, stop_order={"id": "2"},
        filled_quantity=1.0, filled_price=100.0,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with patch("autotrading.cli.open_long", return_value=fake_result) as mock_open_long:
            with patch(
                "autotrading.cli.make_futures_demo_client"
            ) as mock_make_client:
                mock_client = mock_make_client.return_value
                mock_client.fetch_balance.return_value = {"USDT": {"total": 1000.0}}
                exit_code = main(
                    ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
                )
            mock_open_long.assert_called_once()

    assert exit_code == 0


def test_trade_already_long_is_noop_even_with_confirm(tmp_path):
    patches = common_patches(tmp_path, flat_position=False)
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6]:
        with patch("autotrading.cli.make_futures_demo_client") as mock_make_client:
            mock_make_client.return_value.fetch_balance.return_value = {"USDT": {"total": 1000.0}}
            with patch("autotrading.cli.open_long") as mock_open_long, patch(
                "autotrading.cli.close_position"
            ) as mock_close:
                exit_code = main(
                    ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
                )
                mock_open_long.assert_not_called()
                mock_close.assert_not_called()

    assert exit_code == 0


def test_trade_errors_without_news_config():
    fake_config = SimpleNamespace(news=None)
    with patch("autotrading.cli.load_config", return_value=fake_config):
        exit_code = main(["trade", "--config", "fake.yaml"])
    assert exit_code == 1
