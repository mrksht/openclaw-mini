"""Slack channel adapter — monitors team channels for GitLab MR links.

The bot listens to all channels it's a member of (or a single channel if
SLACK_CHANNEL_ID is set), collects GitLab MR links, and sends a digest
DM to the owner via heartbeat.

Requires slack-bolt + slack-sdk: install with `uv sync --extra slack`

To enable:
1. Create a Slack app at https://api.slack.com/apps with Socket Mode enabled
2. Add bot scopes: channels:history, channels:read, groups:history, groups:read,
   chat:write, im:write, users:read
3. Install app to workspace, invite bot to the channels you want monitored
4. Set env vars: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_OWNER_ID
   Optionally set SLACK_CHANNEL_ID to limit to one channel.
5. Run: uv run openclaw --channel slack
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from openclaw.channels.base import ChannelAdapter
from openclaw.tools.gitlab_mr import GITLAB_MR_PATTERN

logger = logging.getLogger(__name__)


class SlackChannel(ChannelAdapter):
    """Slack channel adapter.

    Listens to all channels the bot is a member of for GitLab MR links.
    Supports DM conversations with the bot owner using the agent router.
    Heartbeat results are delivered as DMs to the owner.
    """

    def __init__(
        self,
        router: Any,
        session_store: Any,
        tool_registry: Any,
        command_queue: Any,
        memory_store: Any,
        bot_token: str,
        app_token: str,
        owner_id: str,
        channel_id: str = "",
    ) -> None:
        self._router = router
        self._session_store = session_store
        self._tool_registry = tool_registry
        self._command_queue = command_queue
        self._memory_store = memory_store
        self._bot_token = bot_token
        self._app_token = app_token
        self._owner_id = owner_id
        self._channel_id = channel_id  # optional — if empty, scan all bot channels
        self._thread: threading.Thread | None = None
        self._handler: Any = None

    @property
    def name(self) -> str:
        return "slack"

    def send_dm(self, text: str) -> None:
        """Send a DM to the bot owner via Slack API."""
        try:
            from slack_sdk import WebClient
        except ImportError:
            logger.error("slack_sdk not installed — cannot send DM")
            return

        client = WebClient(token=self._bot_token)
        try:
            # Open a DM channel with the owner
            resp = client.conversations_open(users=[self._owner_id])
            dm_channel = resp["channel"]["id"]

            # Slack message limit is ~40k chars, but keep it readable
            if len(text) > 3900:
                chunks = []
                while text:
                    if len(text) <= 3900:
                        chunks.append(text)
                        break
                    split_at = text.rfind("\n", 0, 3900)
                    if split_at == -1:
                        split_at = 3900
                    chunks.append(text[:split_at])
                    text = text[split_at:].lstrip("\n")
                for chunk in chunks:
                    client.chat_postMessage(channel=dm_channel, text=chunk)
            else:
                client.chat_postMessage(channel=dm_channel, text=text)
        except Exception as e:
            logger.error("Failed to send Slack DM: %s", e)
            print(f"  ⚠️  Failed to send Slack DM: {e}")

    def _get_bot_channels(self, client) -> list[dict]:
        """Discover all channels the bot is a member of.

        Returns list of {id, name} dicts.
        Tries public+private first, falls back to public-only if groups:read
        scope is missing.
        """
        channels: list[dict] = []
        channel_types = "public_channel,private_channel"

        for attempt in range(2):
            try:
                cursor = None
                while True:
                    kwargs: dict[str, Any] = {
                        "types": channel_types,
                        "exclude_archived": True,
                        "limit": 200,
                    }
                    if cursor:
                        kwargs["cursor"] = cursor

                    result = client.users_conversations(**kwargs)
                    for ch in result.get("channels", []):
                        channels.append({"id": ch["id"], "name": ch.get("name", ch["id"])})

                    cursor = result.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
                return channels
            except Exception as e:
                err_str = str(e)
                # If missing groups:read, retry with public channels only
                if "missing_scope" in err_str and "groups:read" in err_str and attempt == 0:
                    channel_types = "public_channel"
                    channels = []
                    print("  ℹ️  groups:read scope not available — scanning public channels only")
                    continue
                logger.error("Failed to list bot channels: %s", e)
                print(f"  ⚠️  Could not list bot channels: {e}")
                break

        return channels

    def _fetch_channel_messages(self, hours: int = 24) -> list[dict]:
        """Fetch messages from the last N hours across all bot channels.

        If SLACK_CHANNEL_ID is set, only that channel is scanned.
        Otherwise, all channels the bot is a member of are scanned.

        Returns a list of dicts: {text, user_id, user_name, timestamp, mr_urls, channel_name}.
        Only messages containing GitLab MR links are returned.
        """
        try:
            from slack_sdk import WebClient
        except ImportError:
            logger.error("slack_sdk not installed")
            return []

        client = WebClient(token=self._bot_token)

        # Determine which channels to scan
        if self._channel_id:
            channels_to_scan = [{"id": self._channel_id, "name": self._channel_id}]
        else:
            channels_to_scan = self._get_bot_channels(client)

        if not channels_to_scan:
            print("  ⚠️  Bot is not a member of any channels. Invite it to channels first.")
            return []

        now = datetime.now()
        start = now - timedelta(hours=hours)
        start_ts = str(start.timestamp())
        end_ts = str(now.timestamp())

        ch_names = ", ".join(c["name"] for c in channels_to_scan)
        print(f"  📡 Scanning {len(channels_to_scan)} channel(s): {ch_names}")
        print(f"     Time window: {start.strftime('%Y-%m-%d %H:%M')} → {now.strftime('%Y-%m-%d %H:%M')}")

        mr_messages: list[dict] = []
        user_cache: dict[str, str] = {}  # user_id → display name

        for ch in channels_to_scan:
            try:
                cursor = None
                while True:
                    kwargs: dict[str, Any] = {
                        "channel": ch["id"],
                        "oldest": start_ts,
                        "latest": end_ts,
                        "limit": 200,
                    }
                    if cursor:
                        kwargs["cursor"] = cursor

                    result = client.conversations_history(**kwargs)
                    messages = result.get("messages", [])

                    for msg in messages:
                        if msg.get("subtype"):
                            continue
                        text = msg.get("text", "")
                        user_id = msg.get("user", "unknown")
                        if not text:
                            continue

                        # Extract MR URLs from the message
                        mr_urls = re.findall(
                            r"https?://[^\s<>\"]+/-/merge_requests/\d+", text
                        )
                        if not mr_urls:
                            continue

                        # Resolve user name (cached)
                        if user_id not in user_cache:
                            try:
                                user_info = client.users_info(user=user_id)
                                user_cache[user_id] = user_info["user"].get("real_name", user_id)
                            except Exception:
                                user_cache[user_id] = user_id

                        mr_messages.append({
                            "text": text,
                            "user_id": user_id,
                            "user_name": user_cache[user_id],
                            "timestamp": datetime.fromtimestamp(float(msg.get("ts", 0))).strftime("%Y-%m-%d %H:%M"),
                            "mr_urls": mr_urls,
                            "channel_name": ch["name"],
                        })

                    # Pagination
                    response_metadata = result.get("response_metadata", {})
                    cursor = response_metadata.get("next_cursor")
                    if not cursor:
                        break

            except Exception as e:
                logger.warning("Failed to scan channel %s: %s", ch["name"], e)
                print(f"  ⚠️  Could not scan #{ch['name']}: {e}")

        return mr_messages

    def compile_mr_digest(self, gitlab_url: str | None = None, gitlab_token: str | None = None) -> str:
        """Scan the Slack channel and compile an MR review digest.

        Fetches messages from the last 24 hours, extracts MR links,
        optionally enriches with GitLab API data, and returns a
        formatted digest string.
        """
        mr_messages = self._fetch_channel_messages(hours=24)

        if not mr_messages:
            return "No MR review requests found in the last 24 hours."

        # Deduplicate MR URLs across messages — keep first occurrence with context
        seen_urls: set[str] = set()
        unique_entries: list[dict] = []  # {url, user_name, timestamp, context}

        for msg in mr_messages:
            for url in msg["mr_urls"]:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                unique_entries.append({
                    "url": url,
                    "user_name": msg["user_name"],
                    "timestamp": msg["timestamp"],
                    "context": msg["text"],
                })

        # Optionally enrich with GitLab API data
        mr_details: dict[str, str] = {}
        if gitlab_url and gitlab_token:
            from openclaw.tools.gitlab_mr import _gitlab_api_get, _format_mr_info, GITLAB_MR_PATTERN as MR_PAT
            import urllib.request
            for entry in unique_entries:
                match = MR_PAT.search(entry["url"])
                if not match:
                    continue
                project_path = match.group(1)
                mr_iid = match.group(2)
                encoded_path = urllib.request.quote(project_path, safe="")
                mr_data = _gitlab_api_get(
                    gitlab_url, gitlab_token,
                    f"/projects/{encoded_path}/merge_requests/{mr_iid}",
                )
                if mr_data:
                    # Skip already-merged MRs
                    if mr_data.get("state") == "merged":
                        continue
                    mr_details[entry["url"]] = _format_mr_info(mr_data)

        # Build the digest
        lines = [f"📋 *MR Review Digest* — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
        lines.append(f"Found {len(unique_entries)} MR(s) posted in the last 24 hours:\n")

        for i, entry in enumerate(unique_entries, 1):
            # Skip merged MRs (if we fetched GitLab data and it was merged)
            if gitlab_url and gitlab_token and entry["url"] not in mr_details and entry["url"] in seen_urls:
                # We tried to fetch but it was merged — check if we have details
                pass  # Still show it, just without enrichment

            lines.append(f"{'─' * 40}")
            channel_tag = f" in #{entry.get('channel_name', '?')}" if entry.get("channel_name") else ""
            lines.append(f"*{i}. MR from {entry['user_name']}*{channel_tag} (posted {entry['timestamp']})")
            lines.append(f"🔗 {entry['url']}")

            # Show original message context (truncated)
            context = entry["context"].strip()
            if len(context) > 200:
                context = context[:200] + "…"
            lines.append(f"💬 _{context}_")

            # Show GitLab details if available
            if entry["url"] in mr_details:
                lines.append(f"\n{mr_details[entry['url']]}")

            lines.append("")

        return "\n".join(lines)

    def start(self) -> None:
        """Start the Slack bot with Socket Mode (blocks forever)."""
        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            raise ImportError(
                "slack-bolt and slack-sdk are required for the Slack channel.\n"
                "Install with: uv sync --extra slack"
            )

        from openclaw.config import get_portkey_client

        app = App(token=self._bot_token)
        router = self._router
        session_store = self._session_store
        tool_registry = self._tool_registry
        command_queue = self._command_queue
        channel_id = self._channel_id
        owner_id = self._owner_id

        def _log(msg: str) -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] {msg}", flush=True)

        def _on_tool_use(name: str, inp: dict, result: str) -> None:
            import json as _json
            preview = _json.dumps(inp)
            if len(preview) > 80:
                preview = preview[:77] + "..."
            _log(f"🔧 {name}: {preview}")
            _log(f"   → {str(result)[:120]}")

        # ── Listen to team channel messages (log MR links) ──
        @app.event("message")
        def handle_message_events(event, say, client):
            # Ignore bot messages, edits, etc.
            subtype = event.get("subtype")
            if subtype:
                return

            text = event.get("text", "")
            msg_channel = event.get("channel", "")
            user_id = event.get("user", "")

            if not text:
                return

            # Check if this is a DM
            try:
                conv_info = client.conversations_info(channel=msg_channel)
                is_im = conv_info.get("channel", {}).get("is_im", False)
            except Exception:
                is_im = False

            # If it's a regular channel — log MR links, don't respond
            if not is_im:
                mr_urls = re.findall(
                    r"https?://[^\s<>\"]+/-/merge_requests/\d+", text
                )
                if mr_urls:
                    print(f"  📋 Live: detected {len(mr_urls)} MR link(s) in #{msg_channel}")
                return  # listen-only in channels

            if is_im and user_id == owner_id:
                _log(f"📩 DM from owner: {text}")

                agent, _ = router.resolve(text)
                session_key = f"{agent.session_prefix}:slack:dm:{user_id}"
                _log(f"🤖 Routing to {agent.name} (session: {session_key})")

                try:
                    with command_queue.lock(session_key):
                        response = router.run(
                            client=get_portkey_client(),
                            user_text=text,
                            channel="slack",
                            user_id=f"dm:{user_id}",
                            session_store=session_store,
                            tool_registry=tool_registry,
                            on_tool_use=_on_tool_use,
                        )
                    say(response or "(no response)")
                    _log(f"✅ Response sent")
                except Exception as e:
                    logger.exception("Slack DM handler error")
                    _log(f"❌ Error: {e}")
                    say(f"❌ Error: {e}")

        # Start Socket Mode handler
        self._handler = SocketModeHandler(app, self._app_token)

        # Discover channels on startup
        try:
            from slack_sdk import WebClient
            startup_client = WebClient(token=self._bot_token)
            bot_channels = self._get_bot_channels(startup_client)
            ch_names = [c["name"] for c in bot_channels]
        except Exception as e:
            ch_names = []
            print(f"  ⚠️  Could not list channels on startup: {e}")

        _log("Slack bot starting (Socket Mode)...")
        print("🤖 Slack bot is running!")
        if self._channel_id:
            print(f"   Monitoring channel: {self._channel_id}")
        elif ch_names:
            print(f"   Monitoring {len(ch_names)} channel(s): {', '.join(ch_names)}")
        else:
            print("   ⚠️  Not in any channels yet — invite the bot to channels")
        print(f"   DM target (owner): {owner_id}")
        print("   Press Ctrl+C to stop.\n")

        self._handler.start()

    def stop(self) -> None:
        if self._handler:
            self._handler.close()
            self._handler = None
        logger.info("Slack channel stopped")
