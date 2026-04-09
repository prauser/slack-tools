"""Slack client initialization from environment variables."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from slack_sdk import WebClient

# Load .env from package root, then CWD (CWD takes precedence)
_pkg_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_pkg_root / ".env")
load_dotenv(override=True)


def _require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"Error: {key} is not set. See .env.example", file=sys.stderr)
        sys.exit(1)
    return val


def get_user_client() -> WebClient:
    """Return a WebClient using the User Token (xoxp-).

    Required for search_messages and other user-scoped APIs.
    """
    return WebClient(token=_require_env("SLACK_USER_TOKEN"))


def get_bot_client() -> WebClient:
    """Return a WebClient using the Bot Token (xoxb-).

    Required for chat_postMessage and other bot-scoped APIs.
    """
    return WebClient(token=_require_env("SLACK_BOT_TOKEN"))


def resolve_channel(client: WebClient, channel: str) -> str:
    """Resolve a #channel-name to a channel ID. Pass-through if already an ID."""
    if channel.startswith("C") and channel[1:].isalnum():
        return channel
    # Strip leading #
    name = channel.lstrip("#")
    resp = client.conversations_list(types="public_channel,private_channel", limit=1000)
    for ch in resp["channels"]:
        if ch["name"] == name:
            return ch["id"]
    print(f"Error: channel '{channel}' not found", file=sys.stderr)
    sys.exit(1)


def resolve_user(client: WebClient, user: str) -> str:
    """Resolve a @display-name to a user ID. Pass-through if already an ID."""
    if user.startswith("U") and user[1:].isalnum():
        return user
    name = user.lstrip("@").lower()
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor or "")
        for u in resp["members"]:
            if (
                u.get("name", "").lower() == name
                or u.get("real_name", "").lower() == name
                or u.get("profile", {}).get("display_name", "").lower() == name
            ):
                return u["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    print(f"Error: user '{user}' not found", file=sys.stderr)
    sys.exit(1)
