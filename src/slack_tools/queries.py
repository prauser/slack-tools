"""Read-only Slack operations. All functions return JSON strings."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from slack_sdk import WebClient

from slack_tools.client import resolve_channel


def search_messages(client: WebClient, query: str, count: int = 20, sort: str = "timestamp") -> str:
    """Search messages using Slack's search API (requires user token).

    Parameters
    ----------
    query : str
        Search query (supports Slack search modifiers like ``in:#channel``,
        ``from:@user``, ``before:2026-01-01``).
    count : int
        Max results to return (default 20).
    sort : str
        Sort by "timestamp" (default) or "score".
    """
    resp = client.search_messages(query=query, count=count, sort=sort)
    matches = resp.get("messages", {}).get("matches", [])
    results = []
    for m in matches:
        results.append({
            "ts": m.get("ts"),
            "channel": m.get("channel", {}).get("name", ""),
            "channel_id": m.get("channel", {}).get("id", ""),
            "user": m.get("username", ""),
            "text": m.get("text", ""),
            "permalink": m.get("permalink", ""),
        })
    return json.dumps(results, indent=2, ensure_ascii=False)


def channel_history(
    client: WebClient,
    channel: str,
    since: str | None = None,
    limit: int = 50,
) -> str:
    """Fetch recent messages from a channel.

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    since : str or None
        Time window like "1h", "2d", "30m". If None, fetch latest messages.
    limit : int
        Max messages to return (default 50).
    """
    channel_id = resolve_channel(client, channel)

    kwargs: dict = {"channel": channel_id, "limit": limit}
    if since:
        oldest = _parse_since(since)
        if oldest:
            kwargs["oldest"] = str(oldest)

    resp = client.conversations_history(**kwargs)
    messages = []
    for m in resp.get("messages", []):
        messages.append({
            "ts": m.get("ts"),
            "user": m.get("user", ""),
            "text": m.get("text", ""),
            "thread_ts": m.get("thread_ts"),
            "reply_count": m.get("reply_count", 0),
        })
    # Chronological order (oldest first)
    messages.reverse()
    return json.dumps(messages, indent=2, ensure_ascii=False)


def thread_replies(client: WebClient, channel: str, thread_ts: str) -> str:
    """Fetch all replies in a thread.

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    thread_ts : str
        Timestamp of the thread parent message.
    """
    channel_id = resolve_channel(client, channel)
    resp = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=200)
    messages = []
    for m in resp.get("messages", []):
        messages.append({
            "ts": m.get("ts"),
            "user": m.get("user", ""),
            "text": m.get("text", ""),
        })
    return json.dumps(messages, indent=2, ensure_ascii=False)


def list_users(client: WebClient, query: str | None = None) -> str:
    """List workspace users, optionally filtering by name.

    Parameters
    ----------
    query : str or None
        Substring to filter by (matches name, real_name, display_name).
    """
    users = []
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor or "")
        for u in resp["members"]:
            if u.get("deleted") or u.get("is_bot"):
                continue
            profile = u.get("profile", {})
            entry = {
                "id": u["id"],
                "name": u.get("name", ""),
                "real_name": u.get("real_name", ""),
                "display_name": profile.get("display_name", ""),
                "email": profile.get("email", ""),
                "is_admin": u.get("is_admin", False),
            }
            if query:
                q = query.lower()
                if not any(q in v.lower() for v in [entry["name"], entry["real_name"], entry["display_name"], entry["email"]] if v):
                    continue
            users.append(entry)
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return json.dumps(users, indent=2, ensure_ascii=False)


def list_channels(client: WebClient, query: str | None = None, include_private: bool = False) -> str:
    """List workspace channels.

    Parameters
    ----------
    query : str or None
        Substring to filter channel names.
    include_private : bool
        Whether to include private channels (default False).
    """
    types = "public_channel,private_channel" if include_private else "public_channel"
    channels = []
    cursor = None
    while True:
        resp = client.conversations_list(types=types, limit=200, cursor=cursor or "")
        for ch in resp["channels"]:
            if ch.get("is_archived"):
                continue
            entry = {
                "id": ch["id"],
                "name": ch.get("name", ""),
                "topic": ch.get("topic", {}).get("value", ""),
                "purpose": ch.get("purpose", {}).get("value", ""),
                "num_members": ch.get("num_members", 0),
                "is_private": ch.get("is_private", False),
            }
            if query and query.lower() not in entry["name"].lower():
                continue
            channels.append(entry)
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    channels.sort(key=lambda c: c["num_members"], reverse=True)
    return json.dumps(channels, indent=2, ensure_ascii=False)


def list_usergroups(client: WebClient, include_members: bool = False) -> str:
    """List usergroups (Slack user groups / handles).

    Parameters
    ----------
    include_members : bool
        Whether to include member user IDs for each group.
    """
    resp = client.usergroups_list(include_users=include_members)
    groups = []
    for g in resp.get("usergroups", []):
        if g.get("date_delete", 0) != 0:
            continue
        entry = {
            "id": g["id"],
            "handle": g.get("handle", ""),
            "name": g.get("name", ""),
            "description": g.get("description", ""),
            "user_count": g.get("user_count", 0),
        }
        if include_members:
            entry["members"] = g.get("users", [])
        groups.append(entry)
    return json.dumps(groups, indent=2, ensure_ascii=False)


def _parse_since(since: str) -> float | None:
    """Convert a relative time string (e.g. '2h', '30m', '1d') to a Unix timestamp."""
    since = since.strip().lower()
    now = datetime.now(timezone.utc)
    try:
        if since.endswith("m"):
            delta = timedelta(minutes=int(since[:-1]))
        elif since.endswith("h"):
            delta = timedelta(hours=int(since[:-1]))
        elif since.endswith("d"):
            delta = timedelta(days=int(since[:-1]))
        else:
            return None
        return (now - delta).timestamp()
    except ValueError:
        return None
