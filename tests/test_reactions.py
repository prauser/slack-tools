"""history/thread keep emoji reactions — a ✅ is often the whole reply."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from slack_tools.queries import channel_history, thread_replies

MSG = {"ts": "1.1", "user": "U1", "text": "확인 부탁", "reactions": [
    {"name": "white_check_mark", "users": ["U01E8PW8Q7K"], "count": 1}]}
BARE = {"ts": "1.2", "user": "U2", "text": "no reactions"}


def _client():
    c = MagicMock()
    c.conversations_replies.return_value = {"messages": [MSG, BARE]}
    c.conversations_history.return_value = {"messages": [MSG, BARE], "has_more": False}
    return c


@patch("slack_tools.queries.resolve_channel", side_effect=lambda c, ch: ch)
def test_thread_keeps_reactions(_):
    out = json.loads(thread_replies(_client(), "C1", "1.1"))
    assert out[0]["reactions"] == [{"name": "white_check_mark", "users": ["U01E8PW8Q7K"]}]
    assert out[1]["reactions"] == []


@patch("slack_tools.queries.resolve_channel", side_effect=lambda c, ch: ch)
def test_history_keeps_reactions(_):
    out = {m["ts"]: m for m in json.loads(channel_history(_client(), "C1"))}
    assert out["1.1"]["reactions"][0]["users"] == ["U01E8PW8Q7K"]
    assert out["1.2"]["reactions"] == []
