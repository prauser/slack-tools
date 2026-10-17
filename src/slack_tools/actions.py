"""Write operations for Slack. All functions return JSON strings."""

from __future__ import annotations

import json

from slack_sdk import WebClient

from slack_tools.client import resolve_channel


def load_blocks(path: str) -> list:
    """Read Block Kit blocks from a JSON file: a list, or {"blocks": [...]}.

    Fails loudly on anything else -- a silently dropped layout would post the
    plain-text fallback and look like it worked.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("blocks")
    if not isinstance(data, list) or not data or not all(isinstance(b, dict) and "type" in b for b in data):
        raise ValueError(f"{path}: expected a non-empty list of blocks, each with a 'type'")
    if len(data) > 50:
        raise ValueError(f"{path}: {len(data)} blocks -- Slack allows at most 50 per message")
    return data


def post_message(client: WebClient, channel: str, text: str, blocks: list | None = None) -> str:
    """Post a message to a channel (requires bot token).

    Parameters
    ----------
    channel : str
        Channel ID or #channel-name.
    text : str
        Message text (supports mrkdwn). With ``blocks`` it becomes the
        notification / fallback text.
    blocks : list, optional
        Block Kit blocks.
    """
    channel_id = resolve_channel(client, channel)
    kwargs = {"channel": channel_id, "text": text}
    if blocks:
        kwargs["blocks"] = blocks
    resp = client.chat_postMessage(**kwargs)
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
