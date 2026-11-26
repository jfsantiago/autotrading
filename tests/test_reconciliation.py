from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from autotrading.execution.positions import PositionSide, PositionState
from autotrading.position_tracking import TrackedPosition
from autotrading.reconciliation import reconcile_external_closes
from autotrading.secrets import Secrets


def make_fake_config():
    return SimpleNamespace(
        all_symbols=["BTC/USDT"],
        futures=SimpleNamespace(leverage=4, quote_currency="USDT"),
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


def test_reconcile_skips_when_still_open_and_already_tracked():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.0, entry_price=100.0)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=1.0, entry_price=100.0,
        margin=100.0, opened_at=datetime.now(timezone.utc),
    )
    notify = MagicMock()
    with patch(
        "autotrading.reconciliation.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}
    ), \
         patch("autotrading.reconciliation.track_open_position") as mock_track, \
         patch("autotrading.reconciliation.record_closed_trade") as mock_record, \
         patch("autotrading.reconciliation.untrack_position") as mock_untrack:
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )
    mock_track.assert_not_called()
    mock_record.assert_not_called()
    mock_untrack.assert_not_called()
    notify.assert_not_called()


def test_reconcile_self_heals_untracked_open_position():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.LONG, size=1.0, entry_price=100.0)
    notify = MagicMock()
    with patch("autotrading.reconciliation.fetch_all_tracked_positions", return_value={}), \
         patch("autotrading.reconciliation.track_open_position") as mock_track:
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )
    mock_track.assert_called_once_with(
        make_fake_secrets(), symbol="BTC/USDT", position_side="long", quantity=1.0,
        entry_price=100.0, margin=None,
    )


def test_reconcile_skips_flat_untracked_symbol():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    notify = MagicMock()
    with patch("autotrading.reconciliation.fetch_all_tracked_positions", return_value={}), \
         patch("autotrading.reconciliation.fetch_realized_pnl") as mock_fetch_pnl:
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )
    mock_fetch_pnl.assert_not_called()


def test_reconcile_records_stop_loss_close_when_tracked_long_now_flat():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=2.0, entry_price=100.0,
        margin=50.0, opened_at=datetime.now(timezone.utc),
    )
    notify = MagicMock()
    with patch(
        "autotrading.reconciliation.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}
    ), \
         patch("autotrading.reconciliation.fetch_realized_pnl", return_value=-10.0), \
         patch("autotrading.reconciliation.record_closed_trade") as mock_record, \
         patch("autotrading.reconciliation.untrack_position") as mock_untrack:
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )

    mock_record.assert_called_once_with(
        make_fake_secrets(), symbol="BTC/USDT", position_side="long", quantity=2.0,
        entry_price=100.0, exit_price=95.0, realized_pnl=-10.0, closed_via="stop_loss",
        margin=50.0,
    )
    mock_untrack.assert_called_once_with(make_fake_secrets(), "BTC/USDT")
    notify.assert_called_once()
    assert "STOP-LOSS" in notify.call_args.args[1]


def test_reconcile_records_take_profit_close_when_pnl_positive():
    # Same external-close path, but a positive realized PnL means the
    # take-profit side of the bracket is the one credited, not the stop.
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=2.0, entry_price=100.0,
        margin=50.0, opened_at=datetime.now(timezone.utc),
    )
    notify = MagicMock()
    with patch(
        "autotrading.reconciliation.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}
    ), \
         patch("autotrading.reconciliation.fetch_realized_pnl", return_value=10.0), \
         patch("autotrading.reconciliation.record_closed_trade") as mock_record, \
         patch("autotrading.reconciliation.untrack_position"):
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )

    assert mock_record.call_args.kwargs["closed_via"] == "take_profit"
    assert "TAKE-PROFIT" in notify.call_args.args[1]


def test_reconcile_records_stop_loss_close_for_short():
    position = PositionState(symbol="ETH/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="ETH/USDT", position_side="short", quantity=2.0, entry_price=3000.0,
        margin=50.0, opened_at=datetime.now(timezone.utc),
    )
    notify = MagicMock()
    with patch(
        "autotrading.reconciliation.fetch_all_tracked_positions", return_value={"ETH/USDT": tracked}
    ), \
         patch("autotrading.reconciliation.fetch_realized_pnl", return_value=-20.0), \
         patch("autotrading.reconciliation.record_closed_trade") as mock_record, \
         patch("autotrading.reconciliation.untrack_position"):
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["ETH/USDT"], {"ETH/USDT": position},
            notify,
        )

    assert mock_record.call_args.kwargs["exit_price"] == 3010.0
    assert mock_record.call_args.kwargs["closed_via"] == "stop_loss"


def test_reconcile_leaves_tracked_when_no_realized_pnl_found():
    position = PositionState(symbol="BTC/USDT", side=PositionSide.FLAT, size=0.0, entry_price=None)
    tracked = TrackedPosition(
        symbol="BTC/USDT", position_side="long", quantity=2.0, entry_price=100.0,
        margin=50.0, opened_at=datetime.now(timezone.utc),
    )
    notify = MagicMock()
    with patch(
        "autotrading.reconciliation.fetch_all_tracked_positions", return_value={"BTC/USDT": tracked}
    ), \
         patch("autotrading.reconciliation.fetch_realized_pnl", return_value=None), \
         patch("autotrading.reconciliation.record_closed_trade") as mock_record, \
         patch("autotrading.reconciliation.untrack_position") as mock_untrack:
        reconcile_external_closes(
            make_fake_secrets(), object(), make_fake_config(), ["BTC/USDT"], {"BTC/USDT": position},
            notify,
        )

    mock_record.assert_not_called()
    mock_untrack.assert_not_called()
    notify.assert_not_called()
