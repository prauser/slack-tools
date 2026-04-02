"""Write operations for Slack. All functions return JSON strings."""

from __future__ import annotations

import json

from slack_sdk import WebClient

from slack_tools.client import resolve_channel


def post_message(client: WebClient, channel: str, text: str) -> str:
    """Post a message to a channel (requires bot token).

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    text : str
        Message text (supports mrkdwn).
    """
    channel_id = resolve_channel(client, channel)
    resp = client.chat_postMessage(channel=channel_id, text=text)
    return json.dumps({
        "ok": resp["ok"],
        "channel": resp["channel"],
        "ts": resp["ts"],
    }, indent=2, ensure_ascii=False)


def reply_message(client: WebClient, channel: str, thread_ts: str, text: str) -> str:
    """Reply in a thread (requires bot token).

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    thread_ts : str
        Timestamp of the parent message.
    text : str
        Reply text.
    """
    channel_id = resolve_channel(client, channel)
    resp = client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)
    return json.dumps({
        "ok": resp["ok"],
        "channel": resp["channel"],
        "ts": resp["ts"],
        "thread_ts": resp.get("message", {}).get("thread_ts", thread_ts),
    }, indent=2, ensure_ascii=False)
