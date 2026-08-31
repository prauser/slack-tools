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

    def test_raises_on_a_url_with_an_empty_last_segment(self):
        """FIX [p3]: a trailing slash right after the team id (no list id segment
        at all) used to survive ``rstrip("/")`` and come back out as the *team*
        id ("T0GCQMN07") -- a wrong-but-plausible id that would sail past
        ``list_items`` (which has no F-guard) and fail later with a confusing
        ``list_not_found`` instead of "your URL was malformed"."""
        url = "https://krafton.enterprise.slack.com/lists/T0GCQMN07/"

        with pytest.raises(RuntimeError, match="could not find a Slack List id"):
            parse_list_id(url)

    def test_raises_on_a_bare_non_list_id(self):
        """The guard applies to bare input too, not just URLs -- a team id or any
        other non-F id passed directly is equally wrong-but-plausible."""
        with pytest.raises(RuntimeError, match="could not find a Slack List id"):
            parse_list_id("T0GCQMN07")

    def test_raises_on_an_f_prefixed_id_with_a_punctuation_suffix(self):
        """Round-2 FIX [p4]: the guard's `.isalnum()` clause (mirrored from
        list_comments' own guard, which does have this case in
        TestListCommentsRejectsNonListIds) was unexercised at this call site."""
        with pytest.raises(RuntimeError, match="could not find a Slack List id"):
            parse_list_id("F-123")


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

    def test_walk_all_sends_an_explicit_page_size(self):
        """FIX [p3]: every sibling loop in queries.py sends an explicit page size
        on its walk-all path; this one used to send none at all on ``limit=0``."""
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [_item("Rec1")],
            "response_metadata": {"next_cursor": ""},
        }

        list_items(client, "F0BG5933VUY")

        params = client.api_call.call_args.kwargs["params"]
        assert params["limit"] == 200

    def test_limit_over_one_page_requests_the_remainder_not_the_original_limit(self):
        """FIX [p3]: a limit of 350 used to ask for min(350, 200) == 200 on every
        page, including the second one -- fetching a whole extra page (400 total)
        before trimming down to 350. The second request must ask for the 150
        still needed, not 200 again."""
        client = MagicMock()
        client.api_call.side_effect = _pages(
            {
                "ok": True,
                "items": [_item(f"Rec{i}") for i in range(200)],
                "response_metadata": {"next_cursor": "c2"},
            },
            {
                "ok": True,
                "items": [_item(f"Rec{i}") for i in range(200, 350)],
                "response_metadata": {"next_cursor": ""},
            },
        )

        rows = json.loads(list_items(client, "F0BG5933VUY", limit=350))

        assert len(rows) == 350
        first_params = client.api_call.call_args_list[0].kwargs["params"]
        second_params = client.api_call.call_args_list[1].kwargs["params"]
        assert first_params["limit"] == 200
        assert second_params["limit"] == 150

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

    def test_raises_when_ok_true_but_the_items_key_is_missing(self):
        """FIX [p2]: ``resp.get("items", [])`` used to treat an ok:true response
        with no "items" key at all the same as a genuinely empty list -- the
        worst failure mode for this feature, since it looks like a complete,
        empty result instead of a malformed response."""
        client = MagicMock()
        client.api_call.return_value = {"ok": True, "response_metadata": {"next_cursor": ""}}

        with pytest.raises(RuntimeError, match="no 'items' key"):
            list_items(client, "F0BG5933VUY")

    def test_ok_true_with_a_genuinely_empty_items_list_still_returns_empty(self):
        """The other half of the same fix: a present-but-empty "items" key must
        keep working as a normal empty result, not be mistaken for the missing-key
        error above."""
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": [],
            "response_metadata": {"next_cursor": ""},
        }

        assert json.loads(list_items(client, "F0BG5933VUY")) == []

    def test_raises_when_ok_true_but_the_items_key_is_null(self):
        """Round-2 FIX [p3]: ``null`` is a third response shape, distinct from a
        missing key and from a genuinely empty ``[]`` -- before this fix it hit
        `_required_list`'s ``return resp[key]`` and came back as ``None``, so the
        caller's own iteration/``extend`` would raise a bare, unlabelled
        ``TypeError`` instead of this helper's clear ``RuntimeError``."""
        client = MagicMock()
        client.api_call.return_value = {
            "ok": True,
            "items": None,
            "response_metadata": {"next_cursor": ""},
        }

        with pytest.raises(RuntimeError, match="'items' is null"):
            list_items(client, "F0BG5933VUY")

    def test_rejects_a_negative_limit_from_a_direct_library_caller(self):
        """Round-2 FIX [p3]: click.IntRange only protects the CLI. A caller that
        imports and calls list_items directly must get the same guarantee."""
        client = MagicMock()

        with pytest.raises(RuntimeError, match="limit must be >= 0"):
            list_items(client, "F0BG5933VUY", limit=-1)

        client.api_call.assert_not_called()


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

    def test_raises_when_ok_true_but_the_messages_key_is_missing(self):
        """FIX [p2]: mirrors TestListItems::test_raises_when_ok_true_but_the_items_key_is_missing
        for the top-level history walk -- ``resp.get("messages", [])`` used to
        treat an ok:true response with no "messages" key at all as zero comments,
        indistinguishable from a list that genuinely has none."""
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "response_metadata": {"next_cursor": ""},
        }

        with pytest.raises(RuntimeError, match="no 'messages' key"):
            list_comments(client, "F0BG5933VUY")

    def test_ok_true_with_a_genuinely_empty_messages_list_still_returns_empty(self):
        """The other half of the same fix: a present-but-empty "messages" key
        must keep working as a normal empty result."""
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [],
            "response_metadata": {"next_cursor": ""},
        }

        result = json.loads(list_comments(client, "F0BG5933VUY"))

        assert result["messages"] == []

    def test_raises_when_ok_true_but_the_messages_key_is_null(self):
        """Round-2 FIX [p3]: mirrors TestListItems' null-items test, for the
        top-level history walk's "messages" key."""
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": None,
            "response_metadata": {"next_cursor": ""},
        }

        with pytest.raises(RuntimeError, match="'messages' is null"):
            list_comments(client, "F0BG5933VUY")

    def test_raises_when_ok_true_but_a_reply_pages_messages_key_is_missing(self):
        """Round-2 FIX [p2] BLOCKING: the third collection-read site -- the
        reply-page walk inside `_replies` -- was still a bare
        ``resp.get("messages", [])`` after round 1. An ok:true reply page
        missing "messages" entirely used to be silently read as "no more
        replies" rather than raising, the exact failure mode `_required_list`
        exists to eliminate; round 1 only wired it into the other two sites."""
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
        client.conversations_replies.return_value = {
            "ok": True,
            "response_metadata": {"next_cursor": ""},
        }

        with pytest.raises(RuntimeError, match="no 'messages' key"):
            list_comments(client, "F0BG5933VUY")

    def test_rejects_a_negative_limit_from_a_direct_library_caller(self):
        """Round-2 FIX [p3]: without this, a negative limit passed directly to
        list_comments (bypassing the CLI's click.IntRange) used to reach
        conversations.history and get relabeled as "comment channel not
        reachable ... F→C mapping" -- blaming the wrong mechanism."""
        client = MagicMock()

        with pytest.raises(RuntimeError, match="limit must be >= 0"):
            list_comments(client, "F0BG5933VUY", limit=-1)

        client.conversations_history.assert_not_called()


class TestListsCli:
    def test_lists_help_mentions_both_subcommands(self):
        """FIX [p4]: renamed from a name that claimed to check user-token wiring
        (that's covered separately by test_items_command_wires_the_user_client /
        test_comments_command_wires_the_user_client below) -- this test only ever
        asserted against `--help` text."""
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

    def test_items_command_prints_a_clean_stderr_line_for_a_malformed_url(self):
        """Round-2 FIX [p4]: parse_list_id's RuntimeError (client.py) is correct
        by inspection -- it's raised inside the same `try` the CLI already wraps
        in `except RuntimeError` -- but that path had no end-to-end test. This
        confirms it actually produces the one-line stderr convention rather
        than a traceback, and that the malformed id never reaches the client."""
        user = MagicMock()
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(
                main, ["lists", "items", "https://x.slack.com/lists/T0GCQMN07/"]
            )

        assert result.exit_code == 1
        assert "could not find a Slack List id" in result.stderr
        assert result.stdout == ""
        assert isinstance(result.exception, SystemExit)
        user.api_call.assert_not_called()

    def test_comments_command_prints_a_clean_stderr_line_for_a_malformed_url(self):
        """Round-2 FIX [p4]: same end-to-end confirmation for `lists comments`."""
        user = MagicMock()
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(
                main, ["lists", "comments", "https://x.slack.com/lists/T0GCQMN07/"]
            )

        assert result.exit_code == 1
        assert "could not find a Slack List id" in result.stderr
        assert result.stdout == ""
        assert isinstance(result.exception, SystemExit)
        user.conversations_history.assert_not_called()

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

    def test_comments_command_lets_an_unexpected_local_bug_raise_a_traceback(self):
        """FIX [p2] decision: a programming bug is not an "expected failure" in
        this repo's one-line-stderr sense, so the CLI boundary deliberately does
        not widen its except clause to catch it -- see
        queries.list_comments.test_a_local_bug_does_not_get_mislabeled_as_channel_not_reachable
        for the query-layer half of this same pin. This test documents the actual
        observed CLI-level behaviour for that choice: CliRunner reports the raw
        exception and a non-zero exit code, with nothing echoed to stdout, rather
        than a clean stderr line."""
        user = MagicMock()
        user.conversations_history.return_value = {
            "ok": True,
            "messages": [{"user": "USLACKBOT", "text": "A comment was added", "reply_count": 1}],
            "response_metadata": {"next_cursor": ""},
        }
        with patch("slack_tools.client.get_user_client", return_value=user):
            result = CliRunner().invoke(main, ["lists", "comments", "F0BG5933VUY"])

        assert result.exit_code == 1
        assert isinstance(result.exception, KeyError)
        assert result.stdout == ""

    def test_items_command_rejects_a_negative_limit(self):
        """FIX [p3]: an unvalidated negative --limit used to be forwarded as-is.
        For `lists items` this reached the Slack client and came back as a raw
        API error; validating at the CLI boundary gives a clear, immediate
        usage error instead."""
        result = CliRunner().invoke(main, ["lists", "items", "F0BG5933VUY", "--limit=-1"])

        assert result.exit_code != 0
        assert "limit" in result.output.lower()

    def test_comments_command_rejects_a_negative_limit(self):
        """FIX [p3]: for `lists comments`, an unvalidated negative --limit used to
        reach conversations.history, which raised an argument error there that
        `_history`'s blanket except relabelled as "comment channel not reachable
        ... F→C mapping" -- blaming the wrong mechanism for a bad CLI argument.
        Validating here means that mislabeling can no longer happen via the CLI."""
        result = CliRunner().invoke(main, ["lists", "comments", "F0BG5933VUY", "--limit=-1"])

        assert result.exit_code != 0
        assert "limit" in result.output.lower()


class TestListCommentsRepliesPagination:
    """conversations.replies caps a page at 200. Stopping there dropped reply 201
    onward with nothing in the output saying so — the only trace was reply_count
    disagreeing with len(replies), which no caller was told to check.
    """

    @staticmethod
    def _thread(reply_count: int, *reply_pages):
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True,
            "messages": [
                {"ts": "1.0", "user": "USLACKBOT", "text": "A comment was added",
                 "reply_count": reply_count}
            ],
            "response_metadata": {"next_cursor": ""},
        }
        client.conversations_replies.side_effect = _pages(*reply_pages)
        return client

    @staticmethod
    def _reply_page(lo: int, hi: int, next_cursor: str = "", with_parent: bool = False):
        msgs = [{"ts": "1.0", "user": "U1", "text": "parent"}] if with_parent else []
        msgs += [{"ts": f"1.{i}", "user": "U9", "text": f"r{i}"} for i in range(lo, hi + 1)]
        return {"ok": True, "messages": msgs,
                "response_metadata": {"next_cursor": next_cursor}}

    def test_walks_every_reply_page_instead_of_truncating_at_one(self):
        client = self._thread(
            250,
            self._reply_page(1, 200, next_cursor="MORE", with_parent=True),
            self._reply_page(201, 250),
        )
        result = json.loads(list_comments(client, "F0BG5933VUY"))
        replies = result["messages"][0]["replies"]

        assert client.conversations_replies.call_count == 2
        assert len(replies) == 250 == result["messages"][0]["reply_count"]
        assert replies[-1]["text"] == "r250"

    def test_the_thread_parent_is_excluded_on_every_page(self):
        client = self._thread(
            3,
            self._reply_page(1, 2, next_cursor="MORE", with_parent=True),
            self._reply_page(3, 3, with_parent=True),
        )
        result = json.loads(list_comments(client, "F0BG5933VUY"))
        replies = result["messages"][0]["replies"]

        assert [r["ts"] for r in replies] == ["1.1", "1.2", "1.3"]

    def test_a_reply_page_that_is_not_ok_still_fails_loudly(self):
        client = self._thread(
            250,
            self._reply_page(1, 200, next_cursor="MORE", with_parent=True),
            {"ok": False, "error": "channel_not_found"},
        )
        with pytest.raises(RuntimeError, match="not reachable"):
            list_comments(client, "F0BG5933VUY")


class TestListCommentsRejectsNonListIds:
    """The F->C swap is a blind string edit. A channel id survives it unchanged,
    so without this guard the command read that channel and returned its real
    messages labelled as list comments — wrong output presented as correct.
    """

    @pytest.mark.parametrize(
        "bad_id",
        [
            "C0ABCDEF",
            "D0ABCDEF",
            "",
            "F",
            "not-an-id",
            # FIX [p4]: an F-prefixed id whose remainder isn't alnum -- without this
            # case, removing the guard's `.isalnum()` clause would break nothing.
            "F-123",
        ],
    )
    def test_refuses_anything_that_is_not_a_list_id(self, bad_id):
        client = MagicMock()
        with pytest.raises(RuntimeError, match="not a Slack List id"):
            list_comments(client, bad_id)
        client.conversations_history.assert_not_called()

    def test_a_real_list_id_still_derives_the_comment_channel(self):
        client = MagicMock()
        client.conversations_history.return_value = {
            "ok": True, "messages": [], "response_metadata": {"next_cursor": ""},
        }
        result = json.loads(list_comments(client, "F0BG5933VUY"))
        assert result["comment_channel"] == "C0BG5933VUY"
        assert result["derived"] is True
