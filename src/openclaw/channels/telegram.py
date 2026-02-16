"""Telegram channel adapter.

Requires python-telegram-bot: install with `uv sync --extra telegram`

To enable:
1. Set TELEGRAM_BOT_TOKEN in .env
2. Install the telegram extra: uv sync --extra telegram
3. Run: uv run openclaw --channel telegram
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from openclaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

# Telegram message limit is 4096 characters
_TG_MAX_LEN = 4096


def _split_message(text: str, max_len: int = _TG_MAX_LEN) -> list[str]:
    """Split long text into chunks that fit Telegram's message limit."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline before limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


class TelegramChannel(ChannelAdapter):
    """Telegram bot channel adapter.

    Bridges Telegram messages to the agent router.
    Each Telegram chat gets its own session key.
    Runs locally via polling (no webhook / no deploy needed).
    """

    def __init__(
        self,
        router: Any,
        session_store: Any,
        tool_registry: Any,
        command_queue: Any,
        bot_token: str,
        on_first_chat: Any = None,
    ) -> None:
        self._router = router
        self._session_store = session_store
        self._tool_registry = tool_registry
        self._command_queue = command_queue
        self._bot_token = bot_token
        self._on_first_chat = on_first_chat
        self._first_chat_captured = False
        self._app: Any = None

    @property
    def name(self) -> str:
        return "telegram"

    def start(self) -> None:
        """Start the Telegram bot with long-polling (blocks forever).

        Call this from the main thread — it runs its own asyncio event loop.
        """
        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                CommandHandler,
                ContextTypes,
                MessageHandler,
                filters,
            )
        except ImportError:
            raise ImportError(
                "python-telegram-bot is required for the Telegram channel.\n"
                "Install with: uv sync --extra telegram"
            )

        from openclaw.config import get_portkey_client

        router = self._router
        session_store = self._session_store
        tool_registry = self._tool_registry
        command_queue = self._command_queue

        def _log(msg: str) -> None:
            """Print to terminal so operator can see bot activity."""
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] {msg}", flush=True)

        def _on_tool_use(name: str, inp: dict, result: str) -> None:
            """Log tool usage to terminal."""
            import json as _json
            preview = _json.dumps(inp)
            if len(preview) > 80:
                preview = preview[:77] + "..."
            _log(f"🔧 {name}: {preview}")
            _log(f"   → {str(result)[:120]}")

        # ── Auto-capture first chat ID for heartbeats ──
        _self = self  # capture for closures

        def _maybe_capture_chat(chat_id: int) -> None:
            if not _self._first_chat_captured and _self._on_first_chat:
                _self._first_chat_captured = True
                _self._on_first_chat(chat_id)

        # ── /start command ──
        async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            chat_id = update.effective_chat.id
            _maybe_capture_chat(chat_id)
            _log(f"📩 /start from chat {chat_id}")
            agent_names = ", ".join(router.agent_names)
            await update.message.reply_text(
                f"👋 Hi! I'm your Mini OpenClaw assistant.\n\n"
                f"Agents: {agent_names}\n"
                f"Commands:\n"
                f"  /new — reset session\n"
                f"  /research <query> — use research agent\n\n"
                f"Just send me a message to get started!"
            )
            _log(f"✅ Sent /start response")

        # ── /new command ──
        async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            _log(f"📩 /new from chat {update.effective_chat.id}")
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            context.user_data["session_suffix"] = ts
            await update.message.reply_text("🔄 Session reset. Fresh start!")
            _log(f"✅ Session reset")

        # ── Regular messages ──
        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user_text = update.message.text
            if not user_text:
                return

            chat_id = str(update.effective_chat.id)
            _maybe_capture_chat(update.effective_chat.id)
            suffix = context.user_data.get("session_suffix", "default")
            user_id = f"{chat_id}:{suffix}"

            _log(f"📩 [{chat_id}] {user_text}")

            # Show "typing..." while LLM responds
            await update.effective_chat.send_action("typing")

            agent, _ = router.resolve(user_text)
            session_key = f"{agent.session_prefix}:telegram:{user_id}"
            _log(f"🤖 Routing to {agent.name} (session: {session_key})")

            try:
                with command_queue.lock(session_key):
                    response = router.run(
                        client=get_portkey_client(),
                        user_text=user_text,
                        channel="telegram",
                        user_id=user_id,
                        session_store=session_store,
                        tool_registry=tool_registry,
                        on_tool_use=_on_tool_use,
                    )

                # Split long responses to fit Telegram's 4096 char limit
                resp_preview = (response or "(no response)")[:100]
                _log(f"✅ Response: {resp_preview}{'...' if len(response or '') > 100 else ''}")
                for chunk in _split_message(response or "(no response)"):
                    await update.message.reply_text(chunk)

            except Exception as e:
                logger.exception("Telegram handler error")
                _log(f"❌ Error: {e}")
                await update.message.reply_text(f"❌ Error: {e}")

        # ── /research command ──
        async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            query = " ".join(context.args) if context.args else ""
            if not query:
                await update.message.reply_text("Usage: /research <your query>")
                return

            user_text = f"/research {query}"
            chat_id = str(update.effective_chat.id)
            suffix = context.user_data.get("session_suffix", "default")
            user_id = f"{chat_id}:{suffix}"

            _log(f"📩 [{chat_id}] {user_text}")
            await update.effective_chat.send_action("typing")

            agent, cleaned = router.resolve(user_text)
            session_key = f"{agent.session_prefix}:telegram:{user_id}"
            _log(f"🤖 Routing to {agent.name} (session: {session_key})")

            try:
                with command_queue.lock(session_key):
                    response = router.run(
                        client=get_portkey_client(),
                        user_text=user_text,
                        channel="telegram",
                        user_id=user_id,
                        session_store=session_store,
                        tool_registry=tool_registry,
                        on_tool_use=_on_tool_use,
                    )

                resp_preview = (response or "(no response)")[:100]
                _log(f"✅ Response: {resp_preview}{'...' if len(response or '') > 100 else ''}")
                for chunk in _split_message(response or "(no response)"):
                    await update.message.reply_text(chunk)
            except Exception as e:
                logger.exception("Research handler error")
                _log(f"❌ Error: {e}")
                await update.message.reply_text(f"❌ Error: {e}")

        # Build and run the bot
        self._app = (
            ApplicationBuilder()
            .token(self._bot_token)
            .build()
        )
        self._app.add_handler(CommandHandler("start", cmd_start))
        self._app.add_handler(CommandHandler("new", cmd_new))
        self._app.add_handler(CommandHandler("research", cmd_research))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )

        logger.info("Telegram bot starting (polling)...")
        print("🤖 Telegram bot is running! Send a message to your bot.")
        print("   Press Ctrl+C to stop.\n")

        # run_polling() manages its own event loop and blocks
        self._app.run_polling(drop_pending_updates=True)

    def stop(self) -> None:
        if self._app:
            logger.info("Telegram channel stopping...")
            self._app.stop()
        self._app = None
