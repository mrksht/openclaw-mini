"""Entry point for the OpenClaw clone.

Supports two modes:
  1. `openclaw` — launches the interactive REPL (default)
  2. `openclaw --config <path>` — loads config and can start HTTP/channels

Without --config, falls back to env-var driven REPL mode.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from openclaw.channels.repl import run_repl
from openclaw.config import AppConfig


def main():
    parser = argparse.ArgumentParser(description="Mini OpenClaw — AI assistant")
    parser.add_argument("--config", "-c", help="Path to config.json file")
    parser.add_argument(
        "--channel",
        choices=["repl", "http", "telegram", "slack"],
        default="repl",
        help="Channel to start (default: repl)",
    )
    args = parser.parse_args()

    if args.config:
        config = AppConfig.from_file(args.config)
    else:
        # Auto-discover ~/.mini-openclaw/config.json (or OPENCLAW_CONFIG env)
        config = AppConfig.load()

    errors = config.validate()
    if errors:
        print("Config errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    if args.channel == "http":
        _start_http(config)
    elif args.channel == "telegram":
        _start_telegram(config)
    elif args.channel == "slack":
        _start_slack(config)
    else:
        run_repl()


def _start_http(config: AppConfig) -> None:
    """Start the HTTP API channel."""
    try:
        from openclaw.channels.http_api import HttpApiChannel
    except ImportError:
        print("Flask is required for the HTTP channel: uv sync --extra http")
        sys.exit(1)

    from openclaw.config import get_portkey_client, ensure_workspace
    from openclaw.memory.store import MemoryStore
    from openclaw.permissions.manager import PermissionManager
    from openclaw.session.store import SessionStore
    from openclaw.tools.filesystem import create_read_file_tool, create_write_file_tool
    from openclaw.tools.memory_tools import create_memory_search_tool, create_save_memory_tool
    from openclaw.tools.registry import ToolRegistry
    from openclaw.tools.shell import create_shell_tool
    from openclaw.tools.web import create_web_search_tool

    ensure_workspace()
    client = get_portkey_client()
    session_store = SessionStore(config.workspace + "/sessions")
    memory_store = MemoryStore(config.workspace + "/memory")
    pm = PermissionManager(config.workspace + "/exec-approvals.json")
    registry = ToolRegistry()
    registry.register(create_shell_tool(pm))
    registry.register(create_read_file_tool())
    registry.register(create_write_file_tool())
    registry.register(create_save_memory_tool(memory_store))
    registry.register(create_memory_search_tool(memory_store))
    registry.register(create_web_search_tool())

    ch_conf = config.channels.get("http")
    host = ch_conf.host if ch_conf else "0.0.0.0"
    port = ch_conf.port if ch_conf else 5000

    channel = HttpApiChannel(
        client=client,
        model=config.default_model,
        session_store=session_store,
        tool_registry=registry,
        host=host,
        port=port,
    )
    print(f"Starting HTTP API on {host}:{port}")
    channel.start()


def _start_telegram(config: AppConfig) -> None:
    """Start the Telegram bot channel."""
    try:
        from openclaw.channels.telegram import TelegramChannel
    except ImportError:
        print("python-telegram-bot is required: uv sync --extra telegram")
        sys.exit(1)

    import os
    from openclaw.agent.router import AgentConfig, AgentRouter
    from openclaw.agent.soul import load_soul
    from openclaw.config import (
        DEFAULT_MODEL, WORKSPACE_DIR, SESSIONS_DIR, MEMORY_DIR,
        APPROVALS_FILE, SOUL_PATH, ensure_workspace, get_portkey_client,
    )
    from openclaw.memory.store import MemoryStore
    from openclaw.permissions.manager import PermissionManager
    from openclaw.queue.command_queue import CommandQueue
    from openclaw.session.store import SessionStore
    from openclaw.tools.filesystem import create_read_file_tool, create_write_file_tool
    from openclaw.tools.memory_tools import create_memory_search_tool, create_save_memory_tool
    from openclaw.tools.registry import ToolRegistry
    from openclaw.tools.shell import create_shell_tool
    from openclaw.tools.web import create_web_search_tool

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    def _terminal_approval(command: str) -> bool:
        """Prompt the operator in the terminal for command approval."""
        print(f"\n  ⚠️  Telegram user requesting command: {command}")
        try:
            answer = input("  Allow? (y/n): ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    ensure_workspace()
    model = config.default_model or DEFAULT_MODEL

    session_store = SessionStore(SESSIONS_DIR)
    memory_store = MemoryStore(MEMORY_DIR)
    pm = PermissionManager(APPROVALS_FILE, approval_callback=_terminal_approval)
    command_queue = CommandQueue()
    registry = ToolRegistry()
    registry.register(create_shell_tool(pm))
    registry.register(create_read_file_tool())
    registry.register(create_write_file_tool())
    registry.register(create_save_memory_tool(memory_store))
    registry.register(create_memory_search_tool(memory_store))
    registry.register(create_web_search_tool())

    # Multi-agent: Jarvis (default) + Scout (/research)
    jarvis = AgentConfig(
        name="Jarvis", model=model, soul_path=SOUL_PATH,
        session_prefix="agent:main", workspace_path=WORKSPACE_DIR,
    )
    scout_soul = os.path.join(WORKSPACE_DIR, "SCOUT.md")
    scout = AgentConfig(
        name="Scout", model=model,
        soul_path=scout_soul if os.path.exists(scout_soul) else None,
        prefix="/research", session_prefix="agent:research",
        workspace_path=WORKSPACE_DIR,
    )
    router = AgentRouter(default_agent=jarvis, agents=[scout])

    # ── Heartbeat Scheduler ──
    from openclaw.heartbeat.scheduler import HeartbeatScheduler, Heartbeat
    import json as _json
    import urllib.request

    # Auto-detected: captured from the first user who messages the bot
    _owner_chat_id: list[int] = []  # mutable container so closures can update it

    def set_owner_chat_id(chat_id: int) -> None:
        """Capture the first chat ID that interacts with the bot."""
        if not _owner_chat_id:
            _owner_chat_id.append(chat_id)
            print(f"  📌 Heartbeat target auto-set to chat {chat_id}")
            # Start heartbeats now that we know where to send them
            if not heartbeat_scheduler.is_running:
                heartbeat_scheduler.start(check_interval=30)

    def _heartbeat_run_fn(agent_name: str, session_key: str, prompt: str) -> str:
        """Run the agent for a heartbeat."""
        return router.run(
            client=get_portkey_client(),
            user_text=prompt,
            channel="heartbeat",
            user_id=session_key,
            session_store=session_store,
            tool_registry=registry,
        )

    def _send_telegram(text: str) -> None:
        """Send a message to the owner's Telegram chat via Bot API (sync)."""
        if not _owner_chat_id:
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = _json.dumps({"chat_id": _owner_chat_id[0], "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"  ⚠️  Failed to send heartbeat message: {e}")

    def _on_heartbeat_result(name: str, response: str) -> None:
        """Send heartbeat result to the owner's Telegram chat."""
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"⏰ Heartbeat [{name}] at {ts}:\n\n{response}"
        print(f"  [Heartbeat] {name}: {response[:100]}")
        _send_telegram(msg)

    heartbeat_scheduler = HeartbeatScheduler(
        run_fn=_heartbeat_run_fn,
        on_result=_on_heartbeat_result,
    )

    # Load heartbeats from config (defined in config.json)
    for hb_def in config.heartbeats:
        heartbeat_scheduler.add(Heartbeat(
            name=hb_def.name,
            schedule_expr=hb_def.schedule,
            prompt=hb_def.prompt,
            agent=hb_def.agent,
        ))

    hb_names = heartbeat_scheduler.heartbeats
    print("Mini OpenClaw — Telegram")
    print(f"  Model: {model}")
    print(f"  Agents: {', '.join(router.agent_names)}")
    print(f"  Tools: {', '.join(registry.tool_names)}")
    if hb_names:
        print(f"  Heartbeats: {', '.join(hb_names)} (starts on first message)")
    else:
        print("  Heartbeats: none (add to config.json to enable)")
    print()

    channel = TelegramChannel(
        router=router,
        session_store=session_store,
        tool_registry=registry,
        command_queue=command_queue,
        bot_token=bot_token,
        on_first_chat=set_owner_chat_id,
    )
    channel.start()


def _start_slack(config: AppConfig) -> None:
    """Start the Slack channel — monitors team channel for MR links, DMs digest to owner."""
    try:
        from openclaw.channels.slack_ch import SlackChannel
    except ImportError:
        print("slack-bolt and slack-sdk are required: uv sync --extra slack")
        sys.exit(1)

    import os
    from openclaw.agent.router import AgentConfig, AgentRouter
    from openclaw.config import (
        DEFAULT_MODEL, WORKSPACE_DIR, SESSIONS_DIR, MEMORY_DIR,
        APPROVALS_FILE, SOUL_PATH, ensure_workspace, get_portkey_client,
        SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID, SLACK_OWNER_ID,
        GITLAB_URL, GITLAB_PRIVATE_TOKEN,
    )
    from openclaw.memory.store import MemoryStore
    from openclaw.permissions.manager import PermissionManager
    from openclaw.queue.command_queue import CommandQueue
    from openclaw.session.store import SessionStore
    from openclaw.tools.filesystem import create_read_file_tool, create_write_file_tool
    from openclaw.tools.memory_tools import create_memory_search_tool, create_save_memory_tool
    from openclaw.tools.registry import ToolRegistry
    from openclaw.tools.shell import create_shell_tool
    from openclaw.tools.web import create_web_search_tool
    from openclaw.tools.gitlab_mr import create_gitlab_mr_tool

    if not SLACK_BOT_TOKEN:
        print("SLACK_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not SLACK_APP_TOKEN:
        print("SLACK_APP_TOKEN not set in .env (needed for Socket Mode)")
        sys.exit(1)
    if not SLACK_CHANNEL_ID:
        print("  ℹ️  SLACK_CHANNEL_ID not set — bot will scan all channels it's a member of")
    if not SLACK_OWNER_ID:
        print("SLACK_OWNER_ID not set in .env (your Slack member ID for DMs)")
        sys.exit(1)

    ensure_workspace()
    model = config.default_model or DEFAULT_MODEL

    session_store = SessionStore(SESSIONS_DIR)
    memory_store = MemoryStore(MEMORY_DIR)
    pm = PermissionManager(APPROVALS_FILE)
    command_queue = CommandQueue()
    registry = ToolRegistry()
    registry.register(create_shell_tool(pm))
    registry.register(create_read_file_tool())
    registry.register(create_write_file_tool())
    registry.register(create_save_memory_tool(memory_store))
    registry.register(create_memory_search_tool(memory_store))
    registry.register(create_web_search_tool())

    # Register GitLab MR tool if credentials are available
    if GITLAB_PRIVATE_TOKEN:
        registry.register(create_gitlab_mr_tool(GITLAB_URL, GITLAB_PRIVATE_TOKEN))
    else:
        print("  ⚠️  GITLAB_PRIVATE_TOKEN not set — gitlab_mr tool disabled")

    # Multi-agent: Jarvis (default) + Scout (/research)
    jarvis = AgentConfig(
        name="Jarvis", model=model, soul_path=SOUL_PATH,
        session_prefix="agent:main", workspace_path=WORKSPACE_DIR,
    )
    scout_soul = os.path.join(WORKSPACE_DIR, "SCOUT.md")
    scout = AgentConfig(
        name="Scout", model=model,
        soul_path=scout_soul if os.path.exists(scout_soul) else None,
        prefix="/research", session_prefix="agent:research",
        workspace_path=WORKSPACE_DIR,
    )
    router = AgentRouter(default_agent=jarvis, agents=[scout])

    # ── Heartbeat Scheduler (daily MR digest → DM to owner) ──
    from openclaw.heartbeat.scheduler import HeartbeatScheduler, Heartbeat

    channel = SlackChannel(
        router=router,
        session_store=session_store,
        tool_registry=registry,
        command_queue=command_queue,
        memory_store=memory_store,
        bot_token=SLACK_BOT_TOKEN,
        app_token=SLACK_APP_TOKEN,
        owner_id=SLACK_OWNER_ID,
        channel_id=SLACK_CHANNEL_ID,
    )

    def _heartbeat_run_fn(agent_name: str, session_key: str, prompt: str) -> str:
        """Run the agent for a heartbeat.

        For the daily-mr-digest heartbeat, scan the Slack channel directly
        instead of going through the LLM — faster, cheaper, and more reliable.
        """
        if "daily-mr-digest" in session_key:
            return channel.compile_mr_digest(
                gitlab_url=GITLAB_URL,
                gitlab_token=GITLAB_PRIVATE_TOKEN,
            )
        return router.run(
            client=get_portkey_client(),
            user_text=prompt,
            channel="heartbeat",
            user_id=session_key,
            session_store=session_store,
            tool_registry=registry,
        )

    def _on_heartbeat_result(name: str, response: str) -> None:
        """Send heartbeat result as a DM to the owner."""
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"⏰ Heartbeat [{name}] at {ts}:\n\n{response}"
        print(f"  [Heartbeat] {name}: {response[:100]}")
        channel.send_dm(msg)

    heartbeat_scheduler = HeartbeatScheduler(
        run_fn=_heartbeat_run_fn,
        on_result=_on_heartbeat_result,
    )

    # Load heartbeats from config
    for hb_def in config.heartbeats:
        heartbeat_scheduler.add(Heartbeat(
            name=hb_def.name,
            schedule_expr=hb_def.schedule,
            prompt=hb_def.prompt,
            agent=hb_def.agent,
        ))

    # Start heartbeats immediately (we know the owner ID from env)
    if heartbeat_scheduler.heartbeats:
        heartbeat_scheduler.start(check_interval=30)

    hb_names = heartbeat_scheduler.heartbeats
    print("Mini OpenClaw — Slack")
    print(f"  Model: {model}")
    print(f"  Agents: {', '.join(router.agent_names)}")
    print(f"  Tools: {', '.join(registry.tool_names)}")
    if hb_names:
        print(f"  Heartbeats: {', '.join(hb_names)}")
    else:
        print("  Heartbeats: none (add to config.json to enable)")
    print()

    channel.start()


if __name__ == "__main__":
    main()
