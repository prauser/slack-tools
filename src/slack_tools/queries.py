"""Read-only Slack operations. All functions return JSON strings."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from slack_sdk import WebClient

from slack_tools.client import resolve_channel

# Slack's search API rejects a page larger than 100.
_SEARCH_PAGE_SIZE = 100
# Only a backstop for a missing/bogus ``paging.pages``; the reported total is what
# normally ends the walk.
_SEARCH_PAGE_GUARD = 100


def search_messages(client: WebClient, query: str, count: int = 20, sort: str = "timestamp") -> str:
    """Search messages using Slack's search API (requires user token).

    Parameters
    ----------
    query : str
        Search query (supports Slack search modifiers like ``in:#channel``,
        ``from:@user``, ``before:2026-01-01``).
    count : int
        Max results to return (default 20). ``0`` fetches every match, the same
        convention ``channel_history`` uses for *limit*.
    sort : str
        Sort by "timestamp" (default) or "score".
    """
    # Slack caps a search page at 100 matches, so ``count`` is honoured by walking
    # pages rather than by asking for a bigger page.  Without this a query whose
    # total exceeds 100 comes back silently truncated — the caller sees a full-looking
    # list and no indication that the tail was dropped, which is the worst failure
    # mode for anything that reasons about "did I miss something".
    fetch_all = count == 0
    per_page = _SEARCH_PAGE_SIZE if fetch_all else min(count, _SEARCH_PAGE_SIZE)
    matches = []
    page = 1
    while True:
        resp = client.search_messages(query=query, count=per_page, sort=sort, page=page)
        msgs = resp.get("messages", {})
        matches.extend(msgs.get("matches", []))
        # Slack reports the page total, so that — not an arbitrary ceiling — is what
        # ends the walk.  ``_SEARCH_PAGE_GUARD`` only catches a missing/bogus count.
        pages = msgs.get("paging", {}).get("pages", 1) or 1
        if page >= pages or page >= _SEARCH_PAGE_GUARD:
            break
        if not fetch_all and len(matches) >= count:
            break
        page += 1
    results = []
    for m in matches if fetch_all else matches[:count]:
        results.append({
            "ts": m.get("ts"),
            "channel": m.get("channel", {}).get("name", ""),
            "channel_id": m.get("channel", {}).get("id", ""),
            # ``user`` is the stable Slack user id, ``username`` the display handle.
            # Both are surfaced because they serve different jobs: filtering by author
            # needs the id (handles are renameable and bots are absent from
            # ``users.list``, so an id list is the only reliable allow/deny key),
            # while humans reading the output need the handle.  Bot posts carry a
            # normal ``U…`` id here — ``search.messages`` does not set ``bot_id`` —
            # and app/integration posts carry no id at all, only a username.
            "user": m.get("user", ""),
            "username": m.get("username", ""),
            "text": m.get("text", ""),
            "permalink": m.get("permalink", ""),
        })
    return json.dumps(results, indent=2, ensure_ascii=False)


def channel_history(
    client: WebClient,
    channel: str,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> str:
    """Fetch recent messages from a channel.

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    since : str or None
        Start of time window. Relative ("1h", "2d", "30m") or absolute
        ("2026-04-02", "2026-04-02T09:00:00"). If None, no lower bound.
    until : str or None
        End of time window. Same formats as *since*.
        If None, fetch up to the latest messages.
    limit : int
        Max messages to return (default 50).
    """
    channel_id = resolve_channel(client, channel)
    fetch_all = limit == 0

    kwargs: dict = {"channel": channel_id, "limit": min(limit, 200) if not fetch_all else 200}
    if since:
        oldest = _parse_time(since)
        if oldest:
            kwargs["oldest"] = str(oldest)
    if until:
        latest = _parse_time(until)
        if latest:
            kwargs["latest"] = str(latest)

    messages = []
    while True:
        resp = client.conversations_history(**kwargs)
        for m in resp.get("messages", []):
            messages.append({
                "ts": m.get("ts"),
                "user": m.get("user", ""),
                "text": m.get("text", ""),
                "thread_ts": m.get("thread_ts"),
                "reply_count": m.get("reply_count", 0),
                "latest_reply": m.get("latest_reply"),
            })
        if not fetch_all or not resp.get("has_more"):
            break
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        kwargs["cursor"] = cursor

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


def user_display_names(client: WebClient) -> dict[str, str]:
    """Map every workspace ``user_id`` to a human-readable name.

    Cursor-paginated like :func:`list_users` — a single ``users.list`` page tops out
    well below a real workspace, and a partial map shows up as silently unlabelled
    rows rather than as an error.
    """
    names: dict[str, str] = {}
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor or "")
        for u in resp["members"]:
            profile = u.get("profile", {})
            names[u["id"]] = (
                profile.get("display_name") or u.get("real_name") or u.get("name", "")
            )
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return names


def list_dms(client: WebClient, names: dict[str, str] | None = None) -> str:
    """List the authenticated user's DM conversations.

    Needs a User Token with ``im:read`` — DM channels belong to a person, not to a
    bot, so a bot token sees only the DMs the bot itself is part of.  DMs are also
    absent from ``conversations.list`` for public/private types and cannot be
    resolved by name, which is why their ``D…`` ids have to be listed explicitly
    before ``history`` can read them.

    Parameters
    ----------
    names : dict or None
        Optional ``user_id -> display name`` map used to label each DM.
    """
    dms = []
    cursor = None
    while True:
        resp = client.conversations_list(
            types="im", limit=200, cursor=cursor or "", exclude_archived=True
        )
        for ch in resp["channels"]:
            if ch.get("is_user_deleted"):
                continue
            uid = ch.get("user", "")
            latest = ch.get("latest")
            dms.append({
                "id": ch["id"],
                "user": uid,
                "username": (names or {}).get(uid, ""),
                "latest": latest.get("ts", "") if isinstance(latest, dict) else "",
            })
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return json.dumps(dms, indent=2, ensure_ascii=False)


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


class _CommentChannelUnreachable(RuntimeError):
    """Raised by ``list_comments`` when the derived F->C pseudo-channel can't be
    read.

    A ``RuntimeError`` subclass so the CLI boundary keeps turning it into the
    repo's one-line-stderr-and-exit convention, but a distinct type so a caller
    or test can tell "the derived channel guess did not resolve" apart from any
    other ``RuntimeError``. Nothing catches it inside this module — the message
    is built once, at the raise site.
    """


# Type keys Slack attaches to a field alongside its raw ``value``. Order matters:
# a field can legitimately carry both "text" and "rich_text" (see the real payload
# in task-1's 실측 사실), and "text" is the one worth surfacing as the value.
_FIELD_TYPE_KEYS = (
    ("text", "text"),
    ("rich_text", "text"),
    ("user", "user"),
    ("date", "date"),
    ("checkbox", "checkbox"),
    ("select", "select"),
)


def _normalize_list_field(field: dict) -> dict:
    """Normalize one Slack List item field, keeping both id keys and the raw value.

    ``key`` and ``column_id`` can differ (observed in real payloads), so both are
    kept — ``column_id`` is the stable lookup key, ``key`` is whatever alias the
    list happened to use. A type key not in ``_FIELD_TYPE_KEYS`` is preserved as
    ``"unknown"`` with ``raw`` intact rather than silently dropped.
    """
    raw = field.get("value")
    field_type = "unknown"
    value = raw
    for type_key, type_name in _FIELD_TYPE_KEYS:
        if type_key in field:
            field_type = type_name
            value = field[type_key]
            break
    return {
        "column_id": field.get("column_id"),
        "key": field.get("key"),
        "type": field_type,
        "value": value,
        "raw": raw,
    }


def _normalize_list_item(item: dict) -> dict:
    """Normalize one Slack List item. Only fields present in the payload survive —
    a missing field means "unset", not "empty string", so absence is preserved
    rather than backfilled.
    """
    return {
        "id": item.get("id"),
        "list_id": item.get("list_id"),
        "created_by": item.get("created_by"),
        "date_created": item.get("date_created"),
        "updated_by": item.get("updated_by"),
        "updated_timestamp": item.get("updated_timestamp"),
        "fields": [_normalize_list_field(f) for f in item.get("fields", [])],
    }


# The real WebClient raises (SlackApiError) on a logical (ok:false) failure
# instead of ever handing back the dict — see the ``try/except`` below, which
# is the only place that failure signal is actually observed in production.
# No documented page-size cap for this endpoint; capped at the same 200 used
# by conversations.history / conversations.replies for consistency.
_LIST_ITEMS_PAGE_SIZE = 200


def list_items(client: WebClient, list_id: str, limit: int = 0) -> str:
    """Fetch items from a Slack List (requires SLACK_USER_TOKEN with lists:read).

    Bot tokens fail this endpoint with ``list_not_found`` — the list can live in
    a workspace the bot isn't in — so this always needs the user client, never
    a bot fallback.

    Parameters
    ----------
    list_id : str
        Slack List id (``F...``), already resolved from a URL if needed.
    limit : int
        Max items to return (default 0 = walk every page, the same ``0 = all``
        convention as ``channel_history``/``search_messages``).
    """
    fetch_all = limit == 0
    raw_items: list[dict] = []
    cursor = ""
    while True:
        params: dict = {"list_id": list_id, "cursor": cursor}
        if not fetch_all:
            params["limit"] = min(limit, _LIST_ITEMS_PAGE_SIZE)
        try:
            # SlackApiError isn't a RuntimeError, and the CLI boundary only catches
            # RuntimeError, so this call needs its own net rather than relying on
            # the ok:false check below to ever fire. (Ruff doesn't flag this as a
            # blind except: the block ends in a re-raise, not a swallow.)
            resp = client.api_call("slackLists.items.list", params=params)
        except Exception as exc:
            raise RuntimeError(f"Error: slackLists.items.list failed for {list_id}: {exc}") from exc
        if not resp.get("ok", True):
            # Kept as a second guard in case a future SDK version returns instead of
            # raising — cheap, but no longer the only guard (see the except above).
            raise RuntimeError(
                f"Error: slackLists.items.list failed for {list_id}: "
                f"{resp.get('error', 'unknown_error')}"
            )
        raw_items.extend(resp.get("items", []))
        if not fetch_all and len(raw_items) >= limit:
            break
        cursor = resp.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
    items = [_normalize_list_item(i) for i in (raw_items if fetch_all else raw_items[:limit])]
    return json.dumps(items, indent=2, ensure_ascii=False)


def list_comments(client: WebClient, list_id: str, limit: int = 0) -> str:
    """Fetch comments on a Slack List (requires SLACK_USER_TOKEN with lists:read).

    Slack Lists have no comments API. Comments live as thread replies under a
    ``USLACKBOT`` "A comment was added" message, in a pseudo-channel whose id is
    the list id with its leading ``F`` swapped for ``C``. This mapping was
    observed on exactly one list — it is not documented — so a lookup failure
    here must fail loudly rather than come back as an empty (and therefore
    indistinguishable from "no comments") result.

    Parameters
    ----------
    list_id : str
        Slack List id (``F...``), already resolved from a URL if needed.
    limit : int
        Max top-level messages to return (default 0 = all).
    """
    # The F->C swap is a blind string edit, so a non-list id has to be rejected
    # here rather than derived from. A channel id (``C...``) would survive the
    # swap unchanged and this would happily return that channel's real messages
    # labelled as list comments -- wrong output presented as correct, which is
    # worse than an error.
    if not (len(list_id) > 1 and list_id[0] == "F" and list_id[1:].isalnum()):
        raise RuntimeError(
            f"Error: {list_id!r} is not a Slack List id. Expected an id starting "
            "with 'F' (or a Slack Lists URL to parse one from)."
        )
    comment_channel = "C" + list_id[1:]
    fetch_all = limit == 0
    kwargs: dict = {"channel": comment_channel, "limit": min(limit, 200) if not fetch_all else 200}
    messages: list[dict] = []

    def _fail(detail: str) -> None:
        raise _CommentChannelUnreachable(
            f"Error: comment channel {comment_channel} not reachable (derived from "
            f"list id {list_id}; this F→C mapping is observed, not documented): {detail}"
        )

    def _history(**kw: object) -> dict:
        # Only the client call itself is guarded — a bug in the normalization
        # code below (e.g. a malformed message missing "ts") must still surface
        # as a real traceback, not get relabeled as "channel not reachable".
        try:
            resp = client.conversations_history(**kw)
        except Exception as exc:  # noqa: BLE001 — converted to the loud, labelled failure below
            _fail(str(exc))
        if not resp.get("ok", True):
            _fail(resp.get("error", "unknown_error"))
        return resp

    def _replies_page(ts: str, cursor: str) -> dict:
        kw: dict = {"channel": comment_channel, "ts": ts, "limit": 200}
        if cursor:
            kw["cursor"] = cursor
        try:
            resp = client.conversations_replies(**kw)
        except Exception as exc:  # noqa: BLE001 — converted to the loud, labelled failure below
            _fail(str(exc))
        if not resp.get("ok", True):
            _fail(resp.get("error", "unknown_error"))
        return resp

    def _replies(ts: str) -> list[dict]:
        """Walk every page of a comment thread.

        conversations.replies caps a page at 200. Stopping there dropped reply
        201 onward with no signal -- the only trace was reply_count disagreeing
        with len(replies), which nothing surfaced. The top-level loop already
        walks its cursor; this is the same walk one level down.
        """
        out: list[dict] = []
        cursor = ""
        while True:
            resp = _replies_page(ts, cursor)
            out.extend(
                {"ts": r.get("ts"), "user": r.get("user", ""), "text": r.get("text", "")}
                for r in resp.get("messages", [])
                if r.get("ts") != ts
            )
            cursor = resp.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                return out

    while True:
        resp = _history(**kwargs)
        for m in resp.get("messages", []):
            entry = {
                "ts": m.get("ts"),
                "user": m.get("user", ""),
                "text": m.get("text", ""),
                "reply_count": m.get("reply_count", 0),
                "replies": [],
            }
            if m.get("reply_count", 0) > 0:
                entry["replies"] = _replies(m["ts"])
            messages.append(entry)
            # Same "walk until satisfied, then trim" shape as list_items — a
            # single-page shortcut here would silently truncate a bounded
            # --limit read that needs a second page to fill.
            if not fetch_all and len(messages) >= limit:
                break
        if not fetch_all and len(messages) >= limit:
            break
        cursor = resp.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
        kwargs["cursor"] = cursor

    if not fetch_all:
        messages = messages[:limit]

    result = {
        "list_id": list_id,
        "comment_channel": comment_channel,
        "derived": True,
        "messages": messages,
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


def _parse_time(value: str) -> float | None:
    """Convert a time string to a Unix timestamp.

    Accepts relative durations ("30m", "2h", "1d") and absolute timestamps
    ("2026-04-02", "2026-04-02T09:00:00", "2026-04-02T09:00:00+09:00").
    """
    value = value.strip()
    now = datetime.now(timezone.utc)

    # Relative: "30m", "2h", "14d"
    lowered = value.lower()
    try:
        if lowered.endswith("m"):
            return (now - timedelta(minutes=int(lowered[:-1]))).timestamp()
        if lowered.endswith("h"):
            return (now - timedelta(hours=int(lowered[:-1]))).timestamp()
        if lowered.endswith("d"):
            return (now - timedelta(days=int(lowered[:-1]))).timestamp()
    except ValueError:
        pass

    # Absolute: "2026-04-02" or "2026-04-02T09:00:00" or with timezone
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue

    # ISO format with timezone offset (e.g. "2026-04-02T09:00:00+09:00")
    try:
        dt = datetime.fromisoformat(value)
        return dt.timestamp()
    except ValueError:
        return None


# Keep backward compatibility
_parse_since = _parse_time
