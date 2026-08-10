"""dms: enumerating D... ids, and labelling them with counterpart names."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from slack_tools.cli import main
from slack_tools.queries import list_dms, user_display_names


def _pages(*pages):
    """Turn positional page dicts into a cursor-paginated side_effect."""
    seq = list(pages)

    def _call(**kwargs):
        return seq.pop(0)

    return _call


def test_list_dms_enumerates_ids():
    client = MagicMock()
    client.conversations_list.return_value = {
        "channels": [
            {"id": "D001", "user": "U001", "latest": {"ts": "1700000001.0"}},
            {"id": "D002", "user": "U002"},
        ]
    }

    rows = json.loads(list_dms(client))

    assert [r["id"] for r in rows] == ["D001", "D002"]
    assert client.conversations_list.call_args.kwargs["types"] == "im"


def test_list_dms_skips_deactivated_counterparts():
    client = MagicMock()
    client.conversations_list.return_value = {
        "channels": [
            {"id": "D001", "user": "U001"},
            {"id": "D002", "user": "U002", "is_user_deleted": True},
        ]
    }

    rows = json.loads(list_dms(client))

    assert [r["id"] for r in rows] == ["D001"]


def test_list_dms_follows_the_cursor():
    client = MagicMock()
    client.conversations_list.side_effect = _pages(
        {
            "channels": [{"id": "D001", "user": "U001"}],
            "response_metadata": {"next_cursor": "c2"},
        },
        {"channels": [{"id": "D002", "user": "U002"}]},
    )

    rows = json.loads(list_dms(client))

    assert [r["id"] for r in rows] == ["D001", "D002"]


def test_list_dms_labels_from_the_name_map():
    client = MagicMock()
    client.conversations_list.return_value = {"channels": [{"id": "D001", "user": "U001"}]}

    (row,) = json.loads(list_dms(client, names={"U001": "은석"}))

    assert row["username"] == "은석"


def test_list_dms_leaves_unknown_users_blank():
    client = MagicMock()
    client.conversations_list.return_value = {"channels": [{"id": "D001", "user": "U404"}]}

    (row,) = json.loads(list_dms(client, names={"U001": "은석"}))

    assert row["username"] == ""


class TestUserDisplayNames:
    def test_paginates_so_large_workspaces_are_fully_labelled(self):
        """One page is not the whole workspace; a partial map silently loses labels."""
        client = MagicMock()
        client.users_list.side_effect = _pages(
            {
                "members": [{"id": "U001", "profile": {"display_name": "a"}}],
                "response_metadata": {"next_cursor": "c2"},
            },
            {"members": [{"id": "U002", "profile": {"display_name": "b"}}]},
        )

        assert user_display_names(client) == {"U001": "a", "U002": "b"}
        assert client.users_list.call_count == 2

    def test_falls_back_through_real_name_then_name(self):
        client = MagicMock()
        client.users_list.return_value = {
            "members": [
                {"id": "U001", "profile": {"display_name": ""}, "real_name": "Eun Seok"},
                {"id": "U002", "profile": {}, "name": "handle-only"},
            ]
        }

        assert user_display_names(client) == {"U001": "Eun Seok", "U002": "handle-only"}


def test_dms_command_uses_user_token_and_skips_lookup_by_default():
    bot, user = MagicMock(name="bot"), MagicMock(name="user")
    with (
        patch("slack_tools.client.get_bot_client", return_value=bot),
        patch("slack_tools.client.get_user_client", return_value=user),
        patch("slack_tools.queries.list_dms", return_value="[]") as list_dms_mock,
    ):
        result = CliRunner().invoke(main, ["dms"])

    assert result.exit_code == 0, result.output
    assert list_dms_mock.call_args.args[0] is user
    assert list_dms_mock.call_args.kwargs["names"] is None
    bot.users_list.assert_not_called()


def test_dms_resolve_names_looks_up_with_the_bot_token():
    """The DM list is user-scoped, but users.list needs the bot's users:read."""
    bot, user = MagicMock(name="bot"), MagicMock(name="user")
    bot.users_list.return_value = {"members": [{"id": "U001", "profile": {"display_name": "은석"}}]}
    with (
        patch("slack_tools.client.get_bot_client", return_value=bot),
        patch("slack_tools.client.get_user_client", return_value=user),
        patch("slack_tools.queries.list_dms", return_value="[]") as list_dms_mock,
    ):
        result = CliRunner().invoke(main, ["dms", "--resolve-names"])

    assert result.exit_code == 0, result.output
    assert list_dms_mock.call_args.args[0] is user
    assert list_dms_mock.call_args.kwargs["names"] == {"U001": "은석"}
