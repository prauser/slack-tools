"""lists: Slack List items/comments — field normalization and the F->C comment guess."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from slack_sdk.errors import SlackApiError

from slack_tools.cli import main
from slack_tools.client import parse_list_id
from slack_tools.queries import list_comments, list_items


def _pages(*pages):
    """Turn positional page dicts into a call-order side_effect, regardless of call shape."""
    seq = list(pages)

    def _call(*args, **kwargs):
        return seq.pop(0)

    return _call


def _item(item_id: str, fields: list[dict] | None = None) -> dict:
    return {"id": item_id, "list_id": "F0BG5933VUY", "fields": fields or []}


class TestParseListId:
    def test_accepts_a_bare_id(self):
        assert parse_list_id("F0BG5933VUY") == "F0BG5933VUY"

    def test_extracts_the_id_from_a_lists_url(self):
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY"
        assert parse_list_id(url) == "F0BG5933VUY"

    def test_strips_a_query_string(self):
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY?tab=all"
        assert parse_list_id(url) == "F0BG5933VUY"

    def test_strips_a_fragment(self):
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY#row1"
        assert parse_list_id(url) == "F0BG5933VUY"

    def test_strips_a_trailing_slash(self):
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY/"
        assert parse_list_id(url) == "F0BG5933VUY"

    def test_strips_a_trailing_slash_followed_by_a_query_string(self):
        """The trailing slash must not swallow the id, leaving only "?tab=all"."""
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY/?tab=all"
        assert parse_list_id(url) == "F0BG5933VUY"


class TestListItems:
    def test_walks_the_cursor_to_completion(self):
        client = MagicMock()
        client.api_call.side_effect = _pages(
            {
                "ok": True,
                "items": [_item("Rec1")],
                "response_metadata": {"next_cursor": "c2"},
            },
            {
                "ok": True,
                "items": [_item("Rec2")],
                "response_metadata": {"next_cursor": ""},
            },
        )

        rows = json.loads(list_items(client, "F0BG5933VUY"))

        assert [r["id"] for r in rows] == ["Rec1", "Rec2"]
        assert client.api_call.call_count == 2
        assert client.api_call.call_args_list[0].args[0] == "slackLists.items.list"

    def test_limit_stops_at_n_without_walking_further_pages(self):
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [_item("Rec1"), _item("Rec2"), _item("Rec3")],
            "response_metadata": {"next_cursor": "would-be-page-2"},
        }

        rows = json.loads(list_items(client, "F0BG5933VUY", limit=2))

        assert [r["id"] for r in rows] == ["Rec1", "Rec2"]
        assert client.api_call.call_count == 1

    def test_normalizes_only_the_fields_present_on_each_item(self):
        """Empty fields are dropped by the API, so item.fields length legitimately varies."""
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [
                _item(
                    "Rec1", [{"key": "name", "column_id": "Col0A", "value": "x", "text": "안건1"}]
                ),
                _item(
                    "Rec2",
                    [
                        {"key": "name", "column_id": "Col0A", "value": "x", "text": "안건2"},
                        {"key": "owner", "column_id": "Col0B", "value": "U1", "user": ["U1"]},
                    ],
                ),
            ],
            "response_metadata": {"next_cursor": ""},
        }

        rows = json.loads(list_items(client, "F0BG5933VUY"))

        assert len(rows[0]["fields"]) == 1
        assert len(rows[1]["fields"]) == 2

    def test_preserves_both_key_and_column_id_when_they_differ(self):
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [
                _item(
                    "Rec1",
                    [{"key": "Col0B_alias", "column_id": "Col0B", "value": "U1", "user": ["U1"]}],
                )
            ],
            "response_metadata": {"next_cursor": ""},
        }

        (item,) = json.loads(list_items(client, "F0BG5933VUY"))
        (field,) = item["fields"]

        assert field["key"] == "Col0B_alias"
        assert field["column_id"] == "Col0B"

    @pytest.mark.parametrize(
        ("field", "expected_type", "expected_value"),
        [
            pytest.param(
                {
                    "key": "name",
                    "column_id": "Col0A",
                    "value": "raw-json",
                    "text": "안건 제목",
                    "rich_text": [{"type": "rich_text"}],
                },
                "text",
                "안건 제목",
                id="text",
            ),
            pytest.param(
                {"key": "owner", "column_id": "Col0B", "value": "U1", "user": ["U1"]},
                "user",
                ["U1"],
                id="user",
            ),
            pytest.param(
                {
                    "key": "due",
                    "column_id": "Col0C",
                    "value": "2026-08-18",
                    "date": ["2026-08-18"],
                    "timestamp": [-1],
                },
                "date",
                ["2026-08-18"],
                id="date",
            ),
            pytest.param(
                {"key": "todo_completed", "column_id": "Col00", "value": False, "checkbox": False},
                "checkbox",
                False,
                id="checkbox",
            ),
            pytest.param(
                {"key": "mystery", "column_id": "Col0Z", "value": "???"},
                "unknown",
                "???",
                id="unknown-type-is-preserved-not-dropped",
            ),
            pytest.param(
                {"key": "priority", "column_id": "Col0D", "value": "P1", "select": ["P1"]},
                "select",
                ["P1"],
                id="select",
            ),
            pytest.param(
                {"key": "owner", "column_id": "Col0B", "value": "[]", "user": []},
                "user",
                [],
                id="type-key-present-but-empty-is-still-that-type-not-unknown",
            ),
        ],
    )
    def test_detects_field_type(self, field, expected_type, expected_value):
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [_item("Rec1", [field])],
            "response_metadata": {"next_cursor": ""},
        }

        (item,) = json.loads(list_items(client, "F0BG5933VUY"))
        (norm,) = item["fields"]

        assert norm["type"] == expected_type
        assert norm["value"] == expected_value
        assert norm["raw"] == field["value"]

    def test_item_with_no_fields_normalizes_to_an_empty_fields_list(self):
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [_item("Rec1", fields=[])],
            "response_metadata": {"next_cursor": ""},
        }

        (item,) = json.loads(list_items(client, "F0BG5933VUY"))

        assert item["id"] == "Rec1"
        assert item["fields"] == []

    def test_raises_when_the_response_is_not_ok(self):
        """Kept as a regression test for the ok:false dict-shape guard — a second,
        cheap safety net in case a future SDK version returns instead of raising.
        It is not, on its own, the guard that fires in production (see the test
        below): the real WebClient never hands back this shape for a logical
        failure, it raises instead.
        """
        client = MagicMock()
        client.api_call.return_value = {"ok": False, "error": "list_not_found"}

        with pytest.raises(Exception, match="list_not_found"):
            list_items(client, "F0BG5933VUY")

    def test_fails_loudly_on_a_client_exception_instead_of_returning_empty(self):
        """FIX 6 regression: the real WebClient raises SlackApiError (not a
        RuntimeError, and never an ok:false dict) on a logical failure. Mirrors
        TestListComments::test_fails_loudly_on_a_client_exception_instead_of_returning_empty.
        Before this fix, this exact scenario propagated as a raw SlackApiError,
        which the CLI's `except RuntimeError` boundary (see FIX 5) could not catch.
        """
        client = MagicMock()
        client.api_call.side_effect = SlackApiError(
            "list_not_found", {"ok": False, "error": "list_not_found"}
        )

        with pytest.raises(RuntimeError, match="list_not_found"):
            list_items(client, "F0BG5933VUY")


class TestListComments:
    def test_reports_the_derived_channel_id(self):
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [
                {
                    "ts": "1.0",
                    "user": "USLACKBOT",
                    "text": "A comment was added",
                    "reply_count": 0,
                }
            ],
            "has_more": False,
        }

        result = json.loads(list_comments(client, "F0BG5933VUY"))

        assert result["list_id"] == "F0BG5933VUY"
        assert result["comment_channel"] == "C0BG5933VUY"
        assert result["derived"] is True
        assert len(result["messages"]) == 1
        client.conversations_history.assert_called_once()
        assert client.conversations_history.call_args.kwargs["channel"] == "C0BG5933VUY"

    def test_attaches_thread_replies_for_messages_with_reply_count(self):
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [
                {
                    "ts": "1.0",
                    "user": "USLACKBOT",
                    "text": "A comment was added",
                    "reply_count": 1,
                }
            ],
            "has_more": False,
        }
        client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "1.0", "user": "USLACKBOT", "text": "A comment was added"},
                {"ts": "1.1", "user": "U001", "text": "사람 코멘트"},
            ],
        }

        result = json.loads(list_comments(client, "F0BG5933VUY"))

        (msg,) = result["messages"]
        assert [r["text"] for r in msg["replies"]] == ["사람 코멘트"]

    def test_walks_the_cursor_to_completion(self):
        """A two-page comment feed must not stop after the first page (limit=0=all)."""
        client = MagicMock()
        client.conversations_history.side_effect = _pages(
            {
                "ok": True,
                "messages": [
                    {
                        "ts": "1.0",
                        "user": "USLACKBOT",
                        "text": "A comment was added",
                        "reply_count": 0,
                    }
                ],
                "response_metadata": {"next_cursor": "c2"},
            },
            {
                "ok": True,
                "messages": [
                    {
                        "ts": "2.0",
                        "user": "USLACKBOT",
                        "text": "A comment was added",
                        "reply_count": 0,
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
        )

        result = json.loads(list_comments(client, "F0BG5933VUY"))

        assert [m["ts"] for m in result["messages"]] == ["1.0", "2.0"]
        assert client.conversations_history.call_count == 2

    def test_limit_walks_further_pages_and_returns_exactly_n(self):
        """Regression: --limit N used to stop after one page (silent truncation)
        when N exceeded the first page, and never trimmed to N otherwise."""
        client = MagicMock()
        client.conversations_history.side_effect = _pages(
            {
                "ok": True,
                "messages": [
                    {
                        "ts": "1.0",
                        "user": "USLACKBOT",
                        "text": "A comment was added",
                        "reply_count": 0,
                    }
                ],
                "response_metadata": {"next_cursor": "c2"},
            },
            {
                "ok": True,
                "messages": [
                    {
                        "ts": "2.0",
                        "user": "USLACKBOT",
                        "text": "A comment was added",
                        "reply_count": 0,
                    },
                    {
                        "ts": "3.0",
                        "user": "USLACKBOT",
                        "text": "A comment was added",
                        "reply_count": 0,
                    },
                ],
                "response_metadata": {"next_cursor": ""},
            },
        )

        result = json.loads(list_comments(client, "F0BG5933VUY", limit=2))

        assert [m["ts"] for m in result["messages"]] == ["1.0", "2.0"]
        assert client.conversations_history.call_count == 2

    def test_fails_loudly_when_a_nested_thread_reply_response_is_not_ok(self):
        """A partial read (top-level ok, thread fetch not) must not look complete."""
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [
                {
                    "ts": "1.0",
                    "user": "USLACKBOT",
                    "text": "A comment was added",
                    "reply_count": 1,
                }
            ],
            "response_metadata": {"next_cursor": ""},
        }
        client.conversations_replies.return_value = {"ok": False, "error": "thread_not_found"}

        with pytest.raises(RuntimeError, match="not reachable"):
            list_comments(client, "F0BG5933VUY")

    def test_a_local_bug_does_not_get_mislabeled_as_channel_not_reachable(self):
        """FIX 7 regression: only the two client calls are wrapped now, not the
        normalization code around them. A malformed message (missing "ts" while
        reply_count > 0, so the reply lookup does ``m["ts"]``) is a local bug, not
        a Slack-reachability problem, and must surface as its own real traceback —
        not get relabeled with the "not reachable ... F->C mapping" message, which
        would hide a genuine bug behind an unrelated explanation.
        """
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [{"user": "USLACKBOT", "text": "A comment was added", "reply_count": 1}],
            "response_metadata": {"next_cursor": ""},
        }

        with pytest.raises(KeyError):
            list_comments(client, "F0BG5933VUY")

    def test_fails_loudly_when_the_channel_response_is_not_ok(self):
        client = MagicMock()
        client.conversations_history.return_value = {"ok": False, "error": "channel_not_found"}

        with pytest.raises(RuntimeError, match="not reachable"):
            list_comments(client, "F0BG5933VUY")

    def test_fails_loudly_on_a_client_exception_instead_of_returning_empty(self):
        client = MagicMock()
        client.conversations_history.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="not reachable"):
            list_comments(client, "F0BG5933VUY")


class TestListsCli:
    def test_items_command_uses_the_user_token_and_lists_help_mentions_subcommands(self):
        result = CliRunner().invoke(main, ["lists", "--help"])

        assert result.exit_code == 0, result.output
        assert "items" in result.output
        assert "comments" in result.output

    def test_items_command_wires_the_user_client(self):
        """Exercise the real query layer (not a query-layer patch) so the
        assertion is meaningful: it fails if cli.py ever wires the bot client."""
        bot, user = MagicMock(name="bot"), MagicMock(name="user")
        user.api_call.return_value = {"ok": True, "items": [], "response_metadata": {}}
        with (
            patch("slack_tools.client.get_bot_client", return_value=bot),
            patch("slack_tools.client.get_user_client", return_value=user),
        ):
            result = CliRunner().invoke(main, ["lists", "items", "F0BG5933VUY"])

        assert result.exit_code == 0, result.output
        user.api_call.assert_called_once()
        bot.api_call.assert_not_called()

    def test_items_command_accepts_a_list_url(self):
        user = MagicMock()
        with (
            patch("slack_tools.client.get_user_client", return_value=user),
            patch("slack_tools.queries.list_items", return_value="[]") as list_items_mock,
        ):
            result = CliRunner().invoke(
                main,
                ["lists", "items", "https://x.slack.com/lists/T0GCQMN07/F0BG5933VUY"],
            )

        assert result.exit_code == 0, result.output
        assert list_items_mock.call_args.args[1] == "F0BG5933VUY"

    def test_items_command_fails_loudly_when_the_query_layer_raises(self):
        user = MagicMock()
        with (
            patch("slack_tools.client.get_user_client", return_value=user),
            patch(
                "slack_tools.queries.list_items",
                side_effect=RuntimeError("list_not_found"),
            ),
        ):
            result = CliRunner().invoke(main, ["lists", "items", "F0BG5933VUY"])

        assert result.exit_code != 0

    def test_items_command_prints_a_clean_stderr_line_instead_of_a_traceback(self):
        """FIX 5: the CLI boundary must convert the raised RuntimeError into the
        repo's house style (stderr line + sys.exit(1)), not a raw traceback."""
        user = MagicMock()
        user.api_call.return_value = {"ok": False, "error": "list_not_found"}
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(main, ["lists", "items", "F0BG5933VUY"])

        assert result.exit_code == 1
        assert "Error: slackLists.items.list failed for F0BG5933VUY: list_not_found" in (
            result.stderr
        )
        assert result.stdout == ""
        assert isinstance(result.exception, SystemExit)

    def test_items_command_prints_a_clean_stderr_line_on_the_real_failure_mode(self):
        """FIX 6: the ok:false dict is not what the real WebClient produces on a
        logical failure — it raises SlackApiError instead. Round 3's CLI test above
        only exercised the dict-shape guard; this exercises the failure mode that
        actually occurs, and would have caught FIX 6's bug (an uncaught SlackApiError
        producing an empty stderr and a raw traceback instead)."""
        user = MagicMock()
        user.api_call.side_effect = SlackApiError(
            "list_not_found", {"ok": False, "error": "list_not_found"}
        )
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(main, ["lists", "items", "F0BG5933VUY"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Error: slackLists.items.list failed for F0BG5933VUY" in result.stderr
        assert "list_not_found" in result.stderr
        assert isinstance(result.exception, SystemExit)

    def test_comments_command_prints_a_clean_stderr_line_instead_of_a_traceback(self):
        """FIX 5: same CLI-boundary convention for lists_comments. The message must
        preserve the "observed, not documented" clause verbatim — that wording is
        the whole point of the error."""
        user = MagicMock()
        user.conversations_history.return_value = {"ok": False, "error": "channel_not_found"}
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(main, ["lists", "comments", "F0BG5933VUY"])

        assert result.exit_code == 1
        assert "comment channel C0BG5933VUY not reachable" in result.stderr
        assert "this F→C mapping is observed, not documented" in result.stderr
        assert "channel_not_found" in result.stderr
        assert result.stdout == ""
        assert isinstance(result.exception, SystemExit)

    def test_comments_command_wires_the_user_client(self):
        bot, user = MagicMock(name="bot"), MagicMock(name="user")
        with (
            patch("slack_tools.client.get_bot_client", return_value=bot),
            patch("slack_tools.client.get_user_client", return_value=user),
            patch("slack_tools.queries.list_comments", return_value="{}") as list_comments_mock,
        ):
            result = CliRunner().invoke(main, ["lists", "comments", "F0BG5933VUY"])

        assert result.exit_code == 0, result.output
        assert list_comments_mock.call_args.args[0] is user

    def test_items_help_shows_the_limit_option(self):
        result = CliRunner().invoke(main, ["lists", "items", "--help"])

        assert result.exit_code == 0, result.output
        assert "--limit" in result.output
