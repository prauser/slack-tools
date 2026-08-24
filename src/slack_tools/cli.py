"""Click CLI entry point for slack-tools."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from slack_sdk import WebClient


@click.group()
def main():
    """Slack CLI for AI agents and automation. All output is JSON."""
    pass


@main.command()
@click.argument("query")
@click.option("--count", "-c", default=20, help="Max results (default 20, 0=all)")
@click.option("--sort", "-s", default="timestamp", type=click.Choice(["timestamp", "score"]))
def search(query: str, count: int, sort: str):
    """Search messages (requires SLACK_USER_TOKEN).

    Supports Slack search modifiers: in:#channel, from:@user, before:YYYY-MM-DD, etc.
    """
    from slack_tools.client import get_user_client
    from slack_tools.queries import search_messages

    click.echo(search_messages(get_user_client(), query, count=count, sort=sort))


def _read_client(as_user: bool, channel: str) -> tuple[WebClient, str]:
    """Pick the client for message reads, plus a pre-resolved channel id.

    Bot token only sees channels the bot was invited to — private channels and
    ad-hoc channels fail with ``channel_not_found`` / ``not_in_channel``.  The
    user token sees every channel its owner is in, so ``--as-user`` is the way
    to read a conversation without inviting the bot first.

    ``#channel-name`` → id resolution still needs ``channels:read``/``groups:read``,
    which user tokens typically lack, so names are resolved with the bot client.
    A bare channel id short-circuits ``resolve_channel`` and costs no API call —
    that path needs no bot token at all, which is the only way to reach a DM
    (``D...``): DMs never appear in ``conversations.list``, so a name lookup
    could not find them anyway.
    """
    from slack_tools.client import get_bot_client, get_user_client, is_channel_id, resolve_channel

    if not as_user:
        return get_bot_client(), channel
    if is_channel_id(channel):
        return get_user_client(), channel
    return get_user_client(), resolve_channel(get_bot_client(), channel)


_AS_USER_HELP = (
    "Read with the User Token (xoxp-) instead of the Bot Token. Sees every channel "
    "you belong to, including private ones, with no bot invite. Needs channels:history, "
    "groups:history, im:history and mpim:history user scopes."
)


@main.command()
@click.argument("channel")
@click.option("--since", "-s", default=None, help="Start: 30m, 2h, 1d or 2026-04-02")
@click.option("--until", "-u", default=None, help="End: 30m, 2h, 1d or 2026-04-02")
@click.option("--limit", "-l", default=50, help="Max messages (default 50, 0=all)")
@click.option("--as-user", is_flag=True, help=_AS_USER_HELP)
def history(channel: str, since: str | None, until: str | None, limit: int, as_user: bool):
    """Fetch recent messages from a channel.

    CHANNEL can be a channel ID (C0123...) or #channel-name.
    """
    from slack_tools.queries import channel_history

    client, channel_id = _read_client(as_user, channel)
    click.echo(channel_history(client, channel_id, since=since, until=until, limit=limit))


@main.command()
@click.argument("channel")
@click.argument("thread_ts")
@click.option("--as-user", is_flag=True, help=_AS_USER_HELP)
def thread(channel: str, thread_ts: str, as_user: bool):
    """Fetch all replies in a thread.

    CHANNEL: channel ID or #channel-name.
    THREAD_TS: timestamp of the parent message.
    """
    from slack_tools.queries import thread_replies

    client, channel_id = _read_client(as_user, channel)
    click.echo(thread_replies(client, channel_id, thread_ts))


@main.command()
@click.argument("channel")
@click.argument("text")
def post(channel: str, text: str):
    """Post a message to a channel (requires SLACK_BOT_TOKEN).

    CHANNEL: channel ID or #channel-name.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.actions import post_message

    click.echo(post_message(get_bot_client(), channel, text))


@main.command()
@click.argument("channel")
@click.argument("thread_ts")
@click.argument("text")
def reply(channel: str, thread_ts: str, text: str):
    """Reply in a thread (requires SLACK_BOT_TOKEN).

    CHANNEL: channel ID or #channel-name.
    THREAD_TS: timestamp of the parent message.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.actions import reply_message

    click.echo(reply_message(get_bot_client(), channel, thread_ts, text))


@main.command()
@click.option("--query", "-q", default=None, help="Filter by name/email substring")
def users(query: str | None):
    """List workspace users (requires SLACK_BOT_TOKEN).

    Excludes deleted users and bots. Use --query to filter.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.queries import list_users

    click.echo(list_users(get_bot_client(), query=query))


@main.command()
@click.option("--query", "-q", default=None, help="Filter by channel name substring")
@click.option("--private", "-p", is_flag=True, help="Include private channels")
def channels(query: str | None, private: bool):
    """List workspace channels (requires SLACK_BOT_TOKEN).

    Excludes archived channels. Sorted by member count.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.queries import list_channels

    click.echo(list_channels(get_bot_client(), query=query, include_private=private))


@main.command()
@click.option(
    "--resolve-names", "-n", is_flag=True, help="Label each DM with the counterpart's name"
)
def dms(resolve_names: bool):
    """List your DM conversations (requires SLACK_USER_TOKEN with im:read).

    DMs never appear in `channels` and cannot be resolved by name, so use the
    `D...` ids printed here with `history --as-user`.
    """
    from slack_tools.client import get_bot_client, get_user_client
    from slack_tools.queries import list_dms, user_display_names

    # users.list is a bot scope (users:read); the DM list itself is user-scoped.
    names = user_display_names(get_bot_client()) if resolve_names else None
    click.echo(list_dms(get_user_client(), names=names))


@main.command()
@click.option("--members", "-m", is_flag=True, help="Include member user IDs")
def usergroups(members: bool):
    """List usergroups / handles (requires SLACK_BOT_TOKEN).

    Shows active usergroups. Use --members to include member lists.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.queries import list_usergroups

    click.echo(list_usergroups(get_bot_client(), include_members=members))


@main.group()
def lists():
    """Slack Lists commands (requires SLACK_USER_TOKEN with lists:read)."""


@lists.command(name="items")
@click.argument("list_id")
@click.option("--limit", "-l", default=0, help="Max items (default 0=all)")
def lists_items(list_id: str, limit: int):
    """Fetch items from a Slack List (requires SLACK_USER_TOKEN with lists:read).

    LIST_ID can be a bare list id (F...) or the full Slack Lists URL.
    Bot token is not an option here — this API returns list_not_found for it.
    """
    from slack_tools.client import get_user_client, parse_list_id
    from slack_tools.queries import list_items

    # Let queries.list_items keep raising (it stays a plain, testable library
    # call) — this is the CLI boundary that turns that into the repo's usual
    # one-line-stderr-and-exit convention (see client.py's _require_env /
    # resolve_channel / resolve_user) instead of a raw traceback.
    try:
        click.echo(list_items(get_user_client(), parse_list_id(list_id), limit=limit))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


@lists.command(name="comments")
@click.argument("list_id")
@click.option("--limit", "-l", default=0, help="Max top-level messages (default 0=all)")
def lists_comments(list_id: str, limit: int):
    """Fetch comments on a Slack List (requires SLACK_USER_TOKEN with lists:read).

    LIST_ID can be a bare list id (F...) or the full Slack Lists URL. Comments
    are read from a pseudo-channel id derived from the list id (F -> C swap),
    observed on one list only — see CLAUDE.md's Slack Lists section.
    """
    from slack_tools.client import get_user_client, parse_list_id
    from slack_tools.queries import list_comments

    # Same CLI-boundary convention as lists_items above — queries.list_comments
    # keeps raising for library callers/tests, this just presents it cleanly.
    try:
        click.echo(list_comments(get_user_client(), parse_list_id(list_id), limit=limit))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
