from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from autotrading.cli import _notify_review_summary, _reconcile_stop_loss_closes, main
from autotrading.execution.orders import OrderResult
from autotrading.execution.positions import PositionSide, PositionState
from autotrading.news.pipeline import NewsSnapshot
from autotrading.position_tracking import TrackedPosition
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
        patch("autotrading.cli.fetch_all_tracked_positions", return_value={}),
        patch("autotrading.cli.track_open_position"),
        patch("autotrading.cli.untrack_position"),
    ]


def test_trade_without_confirm_never_places_orders(tmp_path):
    patches = common_patches(tmp_path, flat_position=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
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
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
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
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6], patches[7], patches[8], patches[9]:
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
                }

    assert exit_code == 0


def test_trade_already_long_is_noop_even_with_confirm(tmp_path):
    patches = common_patches(tmp_path, flat_position=False)
    with patches[0], patches[1], patches[2], patches[3], patches[5], patches[6], patches[7], patches[8], patches[9]:
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


def test_notify_review_summary_reports_no_action_when_empty():
    with patch("autotrading.cli.notify_telegram") as mock_notify:
        _notify_review_summary(make_fake_secrets(), {}, [])
    mock_notify.assert_called_once()
    assert "sin operaciones nuevas" in mock_notify.call_args.args[1]


def test_reconcile_skips_when_still_open_and_already_tracked():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.0, entry_price=100.0)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=1.0, entry_price=100.0,
        opened_at=datetime.now(timezone.utc),
    )
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}), \
         patch("autotrading.cli.track_open_position") as mock_track, \
         patch("autotrading.cli.record_closed_trade") as mock_record, \
         patch("autotrading.cli.untrack_position") as mock_untrack:
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position}
        )
    mock_track.assert_not_called()
    mock_record.assert_not_called()
    mock_untrack.assert_not_called()


def test_reconcile_self_heals_untracked_open_position():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.0, entry_price=100.0)
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={}), \
         patch("autotrading.cli.track_open_position") as mock_track:
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position}
        )
    mock_track.assert_called_once_with(
        make_fake_secrets(), symbol="BTC/USDT", position_side="long", quantity=1.0, entry_price=100.0
    )


def test_reconcile_skips_flat_untracked_symbol():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={}), \
         patch("autotrading.cli.fetch_realized_pnl") as mock_fetch_pnl:
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position}
        )
    mock_fetch_pnl.assert_not_called()


def test_reconcile_records_stop_loss_close_when_tracked_long_now_flat():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=2.0, entry_price=100.0,
        opened_at=datetime.now(timezone.utc),
    )
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}), \
         patch("autotrading.cli.fetch_realized_pnl", return_value=10.0), \
         patch("autotrading.cli.record_closed_trade") as mock_record, \
         patch("autotrading.cli.untrack_position") as mock_untrack, \
         patch("autotrading.cli.notify_telegram") as mock_notify:
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position}
        )

    mock_record.assert_called_once_with(
        make_fake_secrets(), symbol="BTC/USDT", position_side="long", quantity=2.0,
        entry_price=100.0, exit_price=105.0, realized_pnl=10.0, closed_via="stop_loss",
    )
    mock_untrack.assert_called_once_with(make_fake_secrets(), "BTC/USDT")
    mock_notify.assert_called_once()
    assert "STOP-LOSS" in mock_notify.call_args.args[1]


def test_reconcile_records_stop_loss_close_for_short():
    position = PositionState(symbol="ETH/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="ETH/USDT", position_side="short", quantity=2.0, entry_price=3000.0,
        opened_at=datetime.now(timezone.utc),
    )
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={"ETH/USDT": tracked}), \
         patch("autotrading.cli.fetch_realized_pnl", return_value=20.0), \
         patch("autotrading.cli.record_closed_trade") as mock_record, \
         patch("autotrading.cli.untrack_position"), \
         patch("autotrading.cli.notify_telegram"):
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["ETH/USDT"], {"ETH/USDT": position}
        )

    assert mock_record.call_args.kwargs["exit_price"] == 2990.0


def test_reconcile_leaves_tracked_when_no_realized_pnl_found():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=2.0, entry_price=100.0,
        opened_at=datetime.now(timezone.utc),
    )
    with patch("autotrading.cli.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}), \
         patch("autotrading.cli.fetch_realized_pnl", return_value=None), \
         patch("autotrading.cli.record_closed_trade") as mock_record, \
         patch("autotrading.cli.untrack_position") as mock_untrack, \
         patch("autotrading.cli.notify_telegram") as mock_notify:
        _reconcile_stop_loss_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position}
        )

    mock_record.assert_not_called()
    mock_untrack.assert_not_called()
    mock_notify.assert_not_called()


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
