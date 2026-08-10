"""End-to-end wiring: --as-user reaches the query layer on both read commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from slack_tools.cli import main


@pytest.fixture
def clients():
    bot, user = MagicMock(name="bot"), MagicMock(name="user")
    with (
        patch("slack_tools.client.get_bot_client", return_value=bot),
        patch("slack_tools.client.get_user_client", return_value=user),
    ):
        yield bot, user


@pytest.mark.parametrize(
    ("argv", "target"),
    [
        pytest.param(["history", "C0123ABC"], "channel_history", id="history"),
        pytest.param(["thread", "C0123ABC", "1700000000.1"], "thread_replies", id="thread"),
    ],
)
def test_read_commands_use_bot_token_by_default(clients, argv, target):
    bot, _ = clients
    with patch(f"slack_tools.queries.{target}", return_value="[]") as query:
        result = CliRunner().invoke(main, argv)

    assert result.exit_code == 0, result.output
    assert query.call_args.args[0] is bot


@pytest.mark.parametrize(
    ("argv", "target"),
    [
        pytest.param(["history", "C0123ABC"], "channel_history", id="history"),
        pytest.param(["thread", "C0123ABC", "1700000000.1"], "thread_replies", id="thread"),
    ],
)
def test_read_commands_use_user_token_with_as_user(clients, argv, target):
    _, user = clients
    with patch(f"slack_tools.queries.{target}", return_value="[]") as query:
        result = CliRunner().invoke(main, [*argv, "--as-user"])

    assert result.exit_code == 0, result.output
    assert query.call_args.args[0] is user


def test_history_reads_a_dm_as_user(clients):
    """The headline case: read a DM with no bot invite and no name lookup."""
    bot, user = clients
    with patch("slack_tools.queries.channel_history", return_value="[]") as query:
        result = CliRunner().invoke(main, ["history", "D0123ABC", "--as-user"])

    assert result.exit_code == 0, result.output
    assert query.call_args.args == (user, "D0123ABC")
    bot.conversations_list.assert_not_called()


def test_as_user_preserves_the_other_history_options(clients):
    """--as-user must not disturb the existing window/limit plumbing."""
    _, user = clients
    with patch("slack_tools.queries.channel_history", return_value="[]") as query:
        result = CliRunner().invoke(
            main, ["history", "C0123ABC", "--since", "2h", "--until", "1h", "-l", "0", "--as-user"]
        )

    assert result.exit_code == 0, result.output
    assert query.call_args.args == (user, "C0123ABC")
    assert query.call_args.kwargs == {"since": "2h", "until": "1h", "limit": 0}
