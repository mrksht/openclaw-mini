"""Discord channel adapter (optional).

Requires discord.py: install with `pip install openclaw-clone[discord]`

This is a stub that provides the structure. To enable:
1. Set DISCORD_BOT_TOKEN in .env
2. Install the discord extra
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from openclaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


class DiscordChannel(ChannelAdapter):
    """Discord bot channel adapter.

    Bridges Discord messages to the agent router.
    Each Discord channel+user gets its own session key.
    """

    def __init__(
        self,
        router: Any,
        session_store: Any,
        tool_registry: Any,
        command_queue: Any,
        bot_token: str,
    ) -> None:
        self._router = router
        self._session_store = session_store
        self._tool_registry = tool_registry
        self._command_queue = command_queue
        self._bot_token = bot_token
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return "discord"

    def start(self) -> None:
        """Start the Discord bot in a background thread."""
        try:
            import discord
        except ImportError:
            raise ImportError(
                "discord.py is required for the Discord channel. "
                "Install with: pip install openclaw-clone[discord]"
            )

        from openclaw.config import get_portkey_client

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message):
            if message.author == client.user:
                return
            if not message.content:
                return

            user_text = message.content
            user_id = f"{message.channel.id}:{message.author.id}"

            agent, _ = self._router.resolve(user_text)
            session_key = f"{agent.session_prefix}:discord:{user_id}"

            try:
                with self._command_queue.lock(session_key):
                    response = self._router.run(
                        client=get_portkey_client(),
                        user_text=user_text,
                        channel="discord",
                        user_id=user_id,
                        session_store=self._session_store,
                        tool_registry=self._tool_registry,
                    )
                await message.channel.send(response[:2000])  # Discord 2k char limit
            except Exception as e:
                logger.exception("Discord handler error")
                await message.channel.send(f"Error: {e}")

        def _run():
            logger.info("Discord bot starting...")
            client.run(self._bot_token)

        self._thread = threading.Thread(target=_run, daemon=True, name="discord-channel")
        self._thread.start()
        logger.info("Discord channel started")

    def stop(self) -> None:
        self._thread = None
        logger.info("Discord channel stopped")
