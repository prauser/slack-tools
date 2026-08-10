"""Which token reads a conversation, and how the channel arg gets resolved.

The contract under test is ``--as-user``: reads go through the user token so
they cover every channel the token owner belongs to, while ``#name`` lookups
still fall back to the bot token (user tokens rarely carry ``channels:read``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from slack_tools.cli import _read_client
from slack_tools.client import is_channel_id


@pytest.fixture
def clients():
    """Patch both token factories; yields (bot, user) sentinels."""
    bot, user = MagicMock(name="bot"), MagicMock(name="user")
    with (
        patch("slack_tools.client.get_bot_client", return_value=bot),
        patch("slack_tools.client.get_user_client", return_value=user),
    ):
        yield bot, user


def test_default_uses_bot_token_and_defers_resolution(clients):
    """Without --as-user nothing changes: bot client, channel passed through raw."""
    bot, _ = clients
    assert _read_client(False, "#general") == (bot, "#general")
    bot.conversations_list.assert_not_called()


@pytest.mark.parametrize(
    "channel",
    [
        pytest.param("C0123ABC", id="public-channel"),
        pytest.param("G0123ABC", id="private-channel-or-group-dm"),
        pytest.param("D0123ABC", id="dm"),
    ],
)
def test_as_user_passes_bare_ids_through_without_touching_bot_token(clients, channel):
    """Every conversation-id prefix short-circuits: no API call, no bot token.

    DMs (``D...``) matter most here — they never appear in conversations.list,
    so a resolution attempt would hard-fail instead of reading the DM.
    """
    bot, user = clients
    assert _read_client(True, channel) == (user, channel)
    bot.conversations_list.assert_not_called()


def test_as_user_resolves_channel_name_with_bot_token(clients):
    """#name needs channels:read, which the user token lacks — so bot resolves it."""
    bot, user = clients
    bot.conversations_list.return_value = {
        "channels": [{"name": "other", "id": "C999"}, {"name": "general", "id": "C0123ABC"}]
    }

    client, channel_id = _read_client(True, "#general")

    # Resolved by the bot, but read by the user.
    assert (client, channel_id) == (user, "C0123ABC")
    bot.conversations_list.assert_called_once()


def test_as_user_exits_when_channel_name_is_unknown(clients):
    bot, _ = clients
    bot.conversations_list.return_value = {"channels": []}

    with pytest.raises(SystemExit) as exc:
        _read_client(True, "#nope")

    assert exc.value.code == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C0123ABC", True),
        ("D0123ABC", True),
        ("G0123ABC", True),
        ("#general", False),
        ("general", False),
        pytest.param("Career-advice", False, id="name-starting-with-C-is-not-an-id"),
        pytest.param("C", False, id="bare-prefix-is-not-an-id"),
        pytest.param("", False, id="empty"),
    ],
)
def test_is_channel_id(value, expected):
    assert is_channel_id(value) is expected
