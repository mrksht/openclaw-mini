"""REPL channel — interactive terminal interface for the agent."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from openclaw.agent.loop import run_agent_turn
from openclaw.agent.router import AgentConfig, AgentRouter
from openclaw.agent.soul import build_system_prompt, load_soul
from openclaw.config import (
    APPROVALS_FILE,
    DEFAULT_MODEL,
    MEMORY_DIR,
    SESSIONS_DIR,
    SOUL_PATH,
    WORKSPACE_DIR,
    get_portkey_client,
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


def _approval_prompt(command: str) -> bool:
    """Interactive approval prompt for shell commands."""
    print(f"\n  \u26a0\ufe0f  Command: {command}")
    try:
        answer = input("  Allow? (y/n): ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _on_tool_use(name: str, tool_input: dict, result: str) -> None:
    """Print tool usage during agent turns."""
    input_preview = json.dumps(tool_input)
    if len(input_preview) > 100:
        input_preview = input_preview[:97] + "..."
    result_preview = str(result)[:150]
    print(f"  \U0001f527 {name}: {input_preview}")
    print(f"     \u2192 {result_preview}")


def _setup_workspace():
    """Ensure workspace directories and default SOUL exist."""
    for d in [WORKSPACE_DIR, SESSIONS_DIR, MEMORY_DIR]:
        os.makedirs(d, exist_ok=True)

    # Copy default SOUL.md if not present
    if not os.path.exists(SOUL_PATH):
        default_soul = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "workspace",
            "SOUL.md",
        )
        if os.path.exists(default_soul):
            shutil.copy2(default_soul, SOUL_PATH)


def _build_registry(memory_store: MemoryStore, permission_manager: PermissionManager) -> ToolRegistry:
    """Build the tool registry with all available tools."""
    registry = ToolRegistry()
    registry.register(create_shell_tool(permission_manager))
    registry.register(create_read_file_tool())
    registry.register(create_write_file_tool())
    registry.register(create_save_memory_tool(memory_store))
    registry.register(create_memory_search_tool(memory_store))
    registry.register(create_web_search_tool())
    return registry


def run_repl():
    """Run the interactive REPL."""
    _setup_workspace()

    # Initialize components
    client = get_portkey_client()
    session_store = SessionStore(SESSIONS_DIR)
    memory_store = MemoryStore(MEMORY_DIR)
    permission_manager = PermissionManager(APPROVALS_FILE, approval_callback=_approval_prompt)
    tool_registry = _build_registry(memory_store, permission_manager)
    command_queue = CommandQueue()

    # Set up multi-agent router
    default_agent = AgentConfig(
        name="Jarvis",
        model=DEFAULT_MODEL,
        soul_path=SOUL_PATH,
        session_prefix="agent:main",
        workspace_path=WORKSPACE_DIR,
    )

    # Research agent — activated via /research prefix
    research_soul = os.path.join(WORKSPACE_DIR, "SCOUT.md")
    research_agent = AgentConfig(
        name="Scout",
        model=DEFAULT_MODEL,
        soul_path=research_soul if os.path.exists(research_soul) else None,
        prefix="/research",
        session_prefix="agent:research",
        workspace_path=WORKSPACE_DIR,
    )

    router = AgentRouter(default_agent=default_agent, agents=[research_agent])

    # Session suffix for this REPL instance
    user_id = "repl"

    print("Mini OpenClaw")
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Workspace: {WORKSPACE_DIR}")
    print(f"  Agents: {', '.join(router.agent_names)}")
    print(f"  Tools: {', '.join(tool_registry.tool_names)}")
    print("  Commands: /new (reset), /research <query>, /quit")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("Goodbye!")
            break
        if user_input.lower() == "/new":
            user_id = f"repl:{datetime.now().strftime('%Y%m%d%H%M%S')}"
            print("  Session reset.\n")
            continue

        # Resolve which agent handles this message
        agent, _ = router.resolve(user_input)
        session_key = f"{agent.session_prefix}:repl:{user_id}"

        try:
            with command_queue.lock(session_key):
                response = router.run(
                    client=client,
                    user_text=user_input,
                    channel="repl",
                    user_id=user_id,
                    session_store=session_store,
                    tool_registry=tool_registry,
                    on_tool_use=_on_tool_use,
                )
            agent_label = agent.name if agent.name != "Jarvis" else "\U0001f916"
            print(f"\n{agent_label} {response}\n")
        except Exception as e:
            print(f"\n\u274c Error: {e}\n")
