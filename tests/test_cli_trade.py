from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from autotrading.cli import _notify_review_summary, main
from autotrading.execution.orders import OrderResult
from autotrading.execution.positions import PositionSide, PositionState
from autotrading.news.pipeline import NewsSnapshot
from autotrading.scheduling import BotState
from autotrading.secrets import Secrets
from autotrading.strategies.base import Signal


def make_fake_config():
    return SimpleNamespace(
        news=SimpleNamespace(output=SimpleNamespace(dir="x", save_csv=False)),
        all_symbols=["BTC/USDT"],
        decision=SimpleNamespace(news_veto_threshold=-0.5, live_lookback_candles=300),
        futures=SimpleNamespace(leverage=4, quote_currency="USDT"),
        risk=SimpleNamespace(position_size_pct=0.04, take_profit_margin_pct=0.24),
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
        patch("autotrading.cli.reconcile_external_closes"),
        patch("autotrading.cli.track_open_position"),
        patch("autotrading.cli.untrack_position"),
        patch("autotrading.cli.ensure_bot_state_row"),
        patch(
            "autotrading.cli.fetch_bot_state",
            return_value=BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=None),
        ),
    ]


def test_trade_without_confirm_never_places_orders(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
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
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
        with patch("autotrading.cli.open_long", return_value=fake_result) as mock_open_long:
            with patch(
                "autotrading.cli.make_futures_demo_client"
            ) as mock_make_client, patch("autotrading.cli.record_closed_trade") as mock_record:
                mock_client = mock_make_client.return_value
                mock_client.fetch_balance.return_value = {"USDT": {"total": 1000.0}}
                exit_code = main(
                    ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
                )
            mock_open_long.assert_called_once()
            mock_record.assert_not_called()  # opens never record trade history

    assert exit_code == 0


def test_trade_with_confirm_closes_long_records_history(tmp_path):
    patches = common_patches(tmp_path, flat_position=False)  # already LONG
    fake_result = OrderResult(
        symbol="BTC/USDT", action="close", entry_order={"id": "3"}, stop_order=None,
        filled_quantity=1.0, filled_price=105.0, realized_pnl=5.0,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
        with patch("autotrading.cli.get_latest_signal", return_value=(Signal.SELL, pd.DataFrame({"close": [105.0]}))):
            with patch("autotrading.cli.close_position", return_value=fake_result) as mock_close:
                with patch(
                    "autotrading.cli.make_futures_demo_client"
                ) as mock_make_client, patch("autotrading.cli.record_closed_trade") as mock_record:
                    mock_make_client.return_value.fetch_balance.return_value = {
                        "USDT": {"total": 1000.0}
                    }
                    exit_code = main(
                        ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
                    )
                mock_close.assert_called_once()
                mock_record.assert_called_once()
                assert mock_record.call_args.kwargs == {
                    "symbol": "BTC/USDT",
                    "position_side": "long",
                    "quantity": 1.0,
                    "entry_price": 100.0,
                    "exit_price": 105.0,
                    "realized_pnl": 5.0,
                    "margin": None,
                }

    assert exit_code == 0


def test_trade_already_long_is_noop_even_with_confirm(tmp_path):
    patches = common_patches(tmp_path, flat_position=False)
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
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


def test_trade_applies_bot_state_leverage_and_risk_overrides(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    override_state = BotState(
        bot_enabled=True, run_interval_minutes=60, last_run_at=None,
        leverage=7, position_size_pct=0.1, take_profit_margin_pct=0.5,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
         patches[7], patches[8], patches[9], patches[10]:
        with patch("autotrading.cli.fetch_bot_state", return_value=override_state):
            with patch("autotrading.cli.open_long") as mock_open_long, patch(
                "autotrading.cli.calculate_position_size"
            ) as mock_calc_size:
                mock_calc_size.return_value = 1.0
                with patch(
                    "autotrading.cli.make_futures_demo_client"
                ) as mock_make_client:
                    mock_make_client.return_value.fetch_balance.return_value = {
                        "USDT": {"total": 1000.0}
                    }
                    main(["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)])

                mock_open_long.assert_called_once()
                assert mock_open_long.call_args.args[3] == 7  # leverage override applied
                assert mock_open_long.call_args.args[4] == 0.5  # take_profit_margin_pct override
                assert mock_calc_size.call_args.args[2] == 7

    assert mock_calc_size.call_args.args[3].position_size_pct == 0.1


def test_trade_rejects_unsafe_leverage_override_from_bot_state(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    unsafe_state = BotState(
        bot_enabled=True, run_interval_minutes=60, last_run_at=None, leverage=50,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
         patches[7], patches[8], patches[9], patches[10]:
        with patch("autotrading.cli.fetch_bot_state", return_value=unsafe_state):
            exit_code = main(
                ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
            )

    assert exit_code == 1


def test_trade_rejects_unsafe_take_profit_override_from_bot_state(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    unsafe_state = BotState(
        bot_enabled=True, run_interval_minutes=60, last_run_at=None,
        take_profit_margin_pct=5.0,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
         patches[7], patches[8], patches[9], patches[10]:
        with patch("autotrading.cli.fetch_bot_state", return_value=unsafe_state):
            exit_code = main(
                ["trade", "--config", "fake.yaml", "--confirm", "--output", str(tmp_path)]
            )

    assert exit_code == 1


def test_trade_errors_without_news_config():
    fake_config = SimpleNamespace(news=None)
    with patch("autotrading.cli.load_config", return_value=fake_config):
        exit_code = main(["trade", "--config", "fake.yaml"])
    assert exit_code == 1


def test_notify_review_summary_reports_no_action_when_empty():
    with patch("autotrading.cli.notify_telegram") as mock_notify:
        _notify_review_summary(make_fake_secrets(), {}, [])
    mock_notify.assert_called_once()
    assert "sin operaciones nuevas" in mock_notify.call_args.args[1]



def test_notify_review_summary_reports_executed_and_failed():
    result = OrderResult(
        symbol="BTC/USDT", action="close", entry_order={"id": "1"}, stop_order=None,
        filled_quantity=1.0, filled_price=105.0, realized_pnl=5.0,
    )
    with patch("autotrading.cli.notify_telegram") as mock_notify:
        _notify_review_summary(
            make_fake_secrets(), {"BTC/USDT": result}, [("ETH/USDT", "insufficient margin")]
        )
    text = mock_notify.call_args.args[1]
    assert "BTC/USDT" in text and "PnL +5.0000" in text
    assert "ETH/USDT" in text and "FALLÓ" in text
