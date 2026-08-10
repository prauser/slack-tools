"""search: page walking, count semantics, and the author-field contract."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from slack_tools.queries import _SEARCH_PAGE_GUARD, search_messages


def _match(i: int, **over):
    m = {
        "ts": f"170000000{i}.0",
        "channel": {"name": "general", "id": "C0123ABC"},
        "user": "U01E8PW8Q7K",
        "username": "isutal",
        "text": f"msg {i}",
        "permalink": "https://example.slack.com/p1",
    }
    m.update(over)
    return m


def _client(total_pages: int, per_page: int = 100, matches=None):
    """A search client serving *total_pages* identical pages."""
    client = MagicMock()

    def _search(query, count, sort, page):
        page_matches = matches if matches is not None else [_match(i) for i in range(per_page)]
        return {"messages": {"matches": page_matches, "paging": {"pages": total_pages}}}

    client.search_messages.side_effect = _search
    return client


def test_single_page_makes_one_call():
    client = _client(total_pages=1, per_page=5)
    assert len(json.loads(search_messages(client, "q", count=20))) == 5
    assert client.search_messages.call_count == 1


def test_walks_pages_to_satisfy_count():
    """Slack caps a page at 100, so >100 requires concatenating pages."""
    client = _client(total_pages=5)

    results = json.loads(search_messages(client, "q", count=250))

    assert len(results) == 250
    assert client.search_messages.call_count == 3  # 100 + 100 + 100, trimmed to 250


def test_stops_once_count_is_met():
    """A satisfied count must not keep paging just because more pages exist."""
    client = _client(total_pages=50)

    json.loads(search_messages(client, "q", count=150))

    assert client.search_messages.call_count == 2


def test_stops_at_last_page_even_if_count_is_unmet():
    """Fewer results than asked is fine; looping past the final page is not."""
    client = _client(total_pages=2)

    results = json.loads(search_messages(client, "q", count=1000))

    assert len(results) == 200
    assert client.search_messages.call_count == 2


def test_count_zero_fetches_everything():
    """0 means "all", matching `history -l 0` — not an empty result."""
    client = _client(total_pages=3)

    results = json.loads(search_messages(client, "q", count=0))

    assert len(results) == 300
    assert client.search_messages.call_count == 3


def test_page_guard_caps_a_bogus_page_total():
    """A missing/absurd paging.pages must not spin forever."""
    client = _client(total_pages=10**9)

    json.loads(search_messages(client, "q", count=0))

    assert client.search_messages.call_count == _SEARCH_PAGE_GUARD


def test_never_asks_for_a_page_over_the_slack_limit():
    client = _client(total_pages=1)

    search_messages(client, "q", count=5000)

    assert client.search_messages.call_args.kwargs["count"] == 100


class TestAuthorFields:
    """`user` is the id, `username` the handle — the 0.2.0 contract."""

    def test_user_is_the_id_and_username_the_handle(self):
        client = _client(total_pages=1, matches=[_match(0)])

        (row,) = json.loads(search_messages(client, "q"))

        assert row["user"] == "U01E8PW8Q7K"
        assert row["username"] == "isutal"

    def test_app_post_has_a_handle_but_no_id(self):
        """App/integration posts carry no user id — an empty string, not a crash."""
        client = _client(total_pages=1, matches=[_match(0, user=None, username="Jenkins")])
        client.search_messages.side_effect = lambda **kw: {
            "messages": {
                "matches": [{"ts": "1", "username": "Jenkins", "text": "build ok"}],
                "paging": {"pages": 1},
            }
        }

        (row,) = json.loads(search_messages(client, "q"))

        assert row["user"] == ""
        assert row["username"] == "Jenkins"

    @pytest.mark.parametrize("field", ["ts", "channel", "channel_id", "user", "username", "text",
                                       "permalink"])
    def test_output_keys_are_stable(self, field):
        client = _client(total_pages=1, matches=[_match(0)])

        (row,) = json.loads(search_messages(client, "q"))

        assert field in row
