from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from autotrading.cli import main
from autotrading.scheduling import BotState
from autotrading.secrets import Secrets


def make_secrets():
    return Secrets(
        openai_api_key="k",
        supabase_db_url="postgresql://fake",
        newsdata_api_key=None,
        coinmarketcal_api_key=None,
    )


def test_scheduled_run_skips_when_bot_disabled():
    disabled_state = BotState(bot_enabled=False, run_interval_minutes=60, last_run_at=None)

    with (
        patch("autotrading.cli.load_secrets", return_value=make_secrets()),
        patch("autotrading.cli.ensure_bot_state_row"),
        patch("autotrading.cli.fetch_bot_state", return_value=disabled_state),
        patch("autotrading.cli.mark_run_completed") as mock_mark,
        patch("autotrading.cli.run_trade_command") as mock_trade,
    ):
        exit_code = main(["scheduled-run", "--config", "fake.yaml"])

    assert exit_code == 0
    mock_trade.assert_not_called()
    mock_mark.assert_not_called()


def test_scheduled_run_skips_when_not_due():
    recent_state = BotState(
        bot_enabled=True,
        run_interval_minutes=60,
        last_run_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    with (
        patch("autotrading.cli.load_secrets", return_value=make_secrets()),
        patch("autotrading.cli.ensure_bot_state_row"),
        patch("autotrading.cli.fetch_bot_state", return_value=recent_state),
        patch("autotrading.cli.mark_run_completed") as mock_mark,
        patch("autotrading.cli.run_trade_command") as mock_trade,
    ):
        exit_code = main(["scheduled-run", "--config", "fake.yaml"])

    assert exit_code == 0
    mock_trade.assert_not_called()
    mock_mark.assert_not_called()


def test_scheduled_run_executes_when_due_and_marks_completed():
    due_state = BotState(
        bot_enabled=True,
        run_interval_minutes=60,
        last_run_at=datetime.now(timezone.utc) - timedelta(minutes=90),
    )

    with (
        patch("autotrading.cli.load_secrets", return_value=make_secrets()),
        patch("autotrading.cli.ensure_bot_state_row"),
        patch("autotrading.cli.fetch_bot_state", return_value=due_state),
        patch("autotrading.cli.mark_run_completed") as mock_mark,
        patch("autotrading.cli.run_trade_command", return_value=0) as mock_trade,
    ):
        exit_code = main(["scheduled-run", "--config", "fake.yaml"])

    assert exit_code == 0
    mock_trade.assert_called_once()
    args_passed = mock_trade.call_args.args[0]
    assert args_passed.confirm is True
    mock_mark.assert_called_once()


def test_scheduled_run_does_not_mark_completed_on_hard_failure():
    due_state = BotState(bot_enabled=True, run_interval_minutes=60, last_run_at=None)

    with (
        patch("autotrading.cli.load_secrets", return_value=make_secrets()),
        patch("autotrading.cli.ensure_bot_state_row"),
        patch("autotrading.cli.fetch_bot_state", return_value=due_state),
        patch("autotrading.cli.mark_run_completed") as mock_mark,
        patch("autotrading.cli.run_trade_command", return_value=1),
    ):
        exit_code = main(["scheduled-run", "--config", "fake.yaml"])

    assert exit_code == 1
    mock_mark.assert_not_called()


def test_scheduled_run_dry_run_bypasses_kill_switch_and_due_check():
    with (
        patch("autotrading.cli.load_secrets", return_value=make_secrets()),
        patch("autotrading.cli.ensure_bot_state_row") as mock_ensure,
        patch("autotrading.cli.fetch_bot_state") as mock_fetch,
        patch("autotrading.cli.mark_run_completed") as mock_mark,
        patch("autotrading.cli.run_trade_command", return_value=0) as mock_trade,
    ):
        exit_code = main(["scheduled-run", "--config", "fake.yaml", "--dry-run"])

    assert exit_code == 0
    mock_ensure.assert_not_called()
    mock_fetch.assert_not_called()
    mock_mark.assert_not_called()
    mock_trade.assert_called_once()
    args_passed = mock_trade.call_args.args[0]
    assert args_passed.confirm is False
