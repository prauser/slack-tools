"""Click CLI entry point for slack-tools."""

from __future__ import annotations

import click


@click.group()
def main():
    """Slack CLI for AI agents and automation. All output is JSON."""
    pass


@main.command()
@click.argument("query")
@click.option("--count", "-c", default=20, help="Max results (default 20)")
@click.option("--sort", "-s", default="timestamp", type=click.Choice(["timestamp", "score"]))
def search(query: str, count: int, sort: str):
    """Search messages (requires SLACK_USER_TOKEN).

    Supports Slack search modifiers: in:#channel, from:@user, before:YYYY-MM-DD, etc.
    """
    from slack_tools.client import get_user_client
    from slack_tools.queries import search_messages

    click.echo(search_messages(get_user_client(), query, count=count, sort=sort))


@main.command()
@click.argument("channel")
@click.option("--since", "-s", default=None, help="Time window: 30m, 2h, 1d")
@click.option("--limit", "-l", default=50, help="Max messages (default 50)")
def history(channel: str, since: str | None, limit: int):
    """Fetch recent messages from a channel.

    CHANNEL can be a channel ID (C0123...) or #channel-name.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.queries import channel_history

    click.echo(channel_history(get_bot_client(), channel, since=since, limit=limit))


@main.command()
@click.argument("channel")
@click.argument("thread_ts")
def thread(channel: str, thread_ts: str):
    """Fetch all replies in a thread.

    CHANNEL: channel ID or #channel-name.
    THREAD_TS: timestamp of the parent message.
    """
    from slack_tools.client import get_bot_client
    from slack_tools.queries import thread_replies

    click.echo(thread_replies(get_bot_client(), channel, thread_ts))


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


if __name__ == "__main__":
    main()
