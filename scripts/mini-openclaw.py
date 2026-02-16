#!/usr/bin/env python3
"""mini-openclaw.py — A complete AI assistant in a single file.

All features from the full OpenClaw clone, condensed into one runnable script:
  • JSONL session persistence (crash-safe)
  • SOUL system prompt from markdown
  • Tool system: shell, read_file, write_file, memory, web_search
  • Permission manager with persistent approvals
  • Context compaction (auto-summarize when context grows)
  • Long-term memory (file-based)
  • Per-session command queue (thread-safe)
  • Heartbeat scheduler (cron-like background tasks)
  • Multi-agent routing (prefix-based)

Usage:
    uv run --with portkey-ai --with python-dotenv --with schedule python scripts/mini-openclaw.py

Or with the project's virtualenv:
    uv run python scripts/mini-openclaw.py

Environment variables:
    PORTKEY_API_KEY       — Portkey gateway API key (required)
    PORTKEY_BASE_URL      — Gateway URL (required)
    OPENCLAW_MODEL        — Model identifier (default: Anthropic Claude Sonnet)
    OPENCLAW_WORKSPACE    — Workspace dir (default: ~/.mini-openclaw)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Generator

# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PORTKEY_API_KEY = os.getenv("PORTKEY_API_KEY", "")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1")
DEFAULT_MODEL = os.getenv(
    "OPENCLAW_MODEL",
    "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
WORKSPACE_DIR = os.path.expanduser(os.getenv("OPENCLAW_WORKSPACE", "~/.mini-openclaw"))
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, "sessions")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
APPROVALS_FILE = os.path.join(WORKSPACE_DIR, "exec-approvals.json")
SOUL_PATH = os.path.join(WORKSPACE_DIR, "SOUL.md")
MAX_TOOL_TURNS = 20
COMPACTION_THRESHOLD = 100_000

DEFAULT_SOUL = """\
# Who You Are

**Name:** Assistant
**Role:** Personal AI assistant

## Personality
- Be genuinely helpful, not performatively helpful
- Skip the "Great question!" — just help
- Have opinions. You're allowed to disagree
- Be concise when needed, thorough when it matters

## Boundaries
- Private things stay private
- When in doubt, ask before acting externally

## Memory
You have a long-term memory system.
- Use save_memory to store important information
- Use memory_search at the start of conversations to recall context
"""

SAFE_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "date", "whoami", "echo",
    "pwd", "which", "git", "python", "python3", "node", "npm", "npx",
    "uv", "pip", "find", "grep", "sort", "uniq", "tr", "cut", "env",
    "file", "ruff", "pytest", "go", "cargo", "make",
})


def get_client():
    """Create a Portkey client."""
    from portkey_ai import Portkey
    return Portkey(api_key=PORTKEY_API_KEY, base_url=PORTKEY_BASE_URL)


def ensure_dirs():
    """Create workspace directories."""
    for d in [WORKSPACE_DIR, SESSIONS_DIR, MEMORY_DIR]:
        os.makedirs(d, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# Session Store (JSONL)
# ═══════════════════════════════════════════════════════════════════

def _sanitize_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", key)


def session_path(key: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{_sanitize_key(key)}.jsonl")


def load_session(key: str) -> list[dict]:
    path = session_path(key)
    if not os.path.exists(path):
        return []
    msgs: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                msgs.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return msgs


def append_msg(key: str, msg: dict) -> None:
    with open(session_path(key), "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def save_session(key: str, msgs: list[dict]) -> None:
    with open(session_path(key), "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════════
# SOUL & System Prompt
# ═══════════════════════════════════════════════════════════════════

def load_soul(path: str | None = None) -> str:
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content
    return DEFAULT_SOUL


def build_system_prompt(soul: str, workspace: str | None = None) -> str:
    parts = [soul, f"\n## Context\n- Current date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    if workspace:
        parts[-1] += f"\n- Workspace: {workspace}"
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# Tool System
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
            for t in self._tools.values()
        ]

    def execute(self, name: str, inp: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        try:
            return str(tool.handler(inp))
        except Exception as e:
            return f"Error executing {name}: {e}"

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


# ═══════════════════════════════════════════════════════════════════
# Permissions
# ═══════════════════════════════════════════════════════════════════

class PermissionManager:
    def __init__(self, approvals_file: str, callback: Callable[[str], bool] | None = None) -> None:
        self._file = approvals_file
        self._callback = callback

    def check(self, command: str) -> str:
        base = command.strip().split()[0] if command.strip() else ""
        if base in SAFE_COMMANDS:
            return "safe"
        approvals = self._load()
        if command in approvals.get("allowed", []):
            return "approved"
        return "needs_approval"

    def request_approval(self, command: str) -> bool:
        approved = self._callback(command) if self._callback else False
        self._save(command, approved)
        return approved

    def _load(self) -> dict:
        if os.path.exists(self._file):
            try:
                with open(self._file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"allowed": [], "denied": []}

    def _save(self, command: str, approved: bool) -> None:
        data = self._load()
        key = "allowed" if approved else "denied"
        if command not in data.get(key, []):
            data.setdefault(key, []).append(command)
        os.makedirs(os.path.dirname(self._file) or ".", exist_ok=True)
        with open(self._file, "w") as f:
            json.dump(data, f, indent=2)


# ═══════════════════════════════════════════════════════════════════
# Memory Store
# ═══════════════════════════════════════════════════════════════════

class MemoryStore:
    def __init__(self, memory_dir: str) -> None:
        self._dir = memory_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, key: str, content: str) -> None:
        with open(os.path.join(self._dir, f"{_sanitize_key(key)}.md"), "w", encoding="utf-8") as f:
            f.write(content)

    def search(self, query: str) -> str:
        if not os.path.exists(self._dir):
            return "No matching memories found."
        words = query.lower().split()
        if not words:
            return "No matching memories found."
        results: list[str] = []
        for fname in sorted(os.listdir(self._dir)):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(self._dir, fname), "r", encoding="utf-8") as f:
                content = f.read()
            if any(w in content.lower() for w in words):
                results.append(f"--- {fname[:-3]} ---\n{content}")
        return "\n\n".join(results) if results else "No matching memories found."


# ═══════════════════════════════════════════════════════════════════
# Built-in Tools
# ═══════════════════════════════════════════════════════════════════

def make_shell_tool(pm: PermissionManager) -> Tool:
    def run_command(inp: dict) -> str:
        cmd = inp["command"]
        safety = pm.check(cmd)
        if safety == "needs_approval":
            if not pm.request_approval(cmd):
                return "Permission denied."
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            out = r.stdout + r.stderr
            return out.strip() if out.strip() else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (30s)"
        except Exception as e:
            return f"Error: {e}"

    return Tool("run_command", "Run a shell command", {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Shell command to run"}},
        "required": ["command"],
    }, run_command)


def make_read_file_tool() -> Tool:
    def read_file(inp: dict) -> str:
        try:
            with open(inp["path"], "r", encoding="utf-8") as f:
                content = f.read(50_000)
            return content + ("\n... (truncated)" if len(content) == 50_000 else "")
        except FileNotFoundError:
            return f"Error: File not found: {inp['path']}"
        except IsADirectoryError:
            return f"Error: Path is a directory: {inp['path']}"
        except Exception as e:
            return f"Error: {e}"

    return Tool("read_file", "Read a file from the filesystem", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path to file"}},
        "required": ["path"],
    }, read_file)


def make_write_file_tool() -> Tool:
    def write_file(inp: dict) -> str:
        try:
            d = os.path.dirname(inp["path"])
            if d:
                os.makedirs(d, exist_ok=True)
            with open(inp["path"], "w", encoding="utf-8") as f:
                f.write(inp["content"])
            return f"Wrote {len(inp['content'])} chars to {inp['path']}"
        except Exception as e:
            return f"Error: {e}"

    return Tool("write_file", "Write content to a file", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }, write_file)


def make_memory_tools(mem: MemoryStore) -> list[Tool]:
    def save_memory(inp: dict) -> str:
        mem.save(inp["key"], inp["content"])
        return f"Saved to memory: {inp['key']}"

    def memory_search(inp: dict) -> str:
        return mem.search(inp["query"])

    return [
        Tool("save_memory", "Save important info to long-term memory", {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short label"},
                "content": {"type": "string", "description": "Info to remember"},
            },
            "required": ["key", "content"],
        }, save_memory),
        Tool("memory_search", "Search long-term memory", {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        }, memory_search),
    ]


def make_web_search_tool() -> Tool:
    def web_search(inp: dict) -> str:
        return f"[Web search stub] Results for: {inp['query']}\nConnect a real search API for actual results."

    return Tool("web_search", "Search the web", {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    }, web_search)


# ═══════════════════════════════════════════════════════════════════
# Context Compaction
# ═══════════════════════════════════════════════════════════════════

def estimate_tokens(msgs: list[dict]) -> int:
    return len(json.dumps(msgs, ensure_ascii=False)) // 4


def compact(msgs: list[dict], client: Any, model: str, threshold: int = COMPACTION_THRESHOLD) -> list[dict]:
    if estimate_tokens(msgs) < threshold:
        return msgs
    mid = len(msgs) // 2
    # Find a user-message boundary near midpoint
    split = mid
    for i in range(mid, len(msgs)):
        if msgs[i].get("role") == "user":
            split = i
            break
    old, recent = msgs[:split], msgs[split:]
    if not old:
        return msgs

    # Summarize old messages
    conv_lines: list[str] = []
    for m in old:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role == "tool":
            conv_lines.append(f"[Tool result]: {content[:500]}")
        elif m.get("tool_calls"):
            names = [tc["function"]["name"] for tc in m["tool_calls"]]
            conv_lines.append(f"Assistant: [called: {', '.join(names)}]")
        else:
            conv_lines.append(f"{role.capitalize()}: {content}")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise conversation summarizer."},
            {"role": "user", "content": (
                "Summarize this conversation concisely. Preserve all important facts, "
                "decisions, file paths, variable names, and outcomes. Bullet list.\n\n"
                + "\n".join(conv_lines)
            )},
        ],
        max_tokens=2048,
    )
    summary = resp.choices[0].message.content or "(empty summary)"
    return [{"role": "user", "content": f"[Summary of {len(old)} earlier messages]\n\n{summary}"}] + recent


# ═══════════════════════════════════════════════════════════════════
# Command Queue (per-session locking)
# ═══════════════════════════════════════════════════════════════════

class CommandQueue:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._meta = threading.Lock()

    @contextmanager
    def lock(self, key: str) -> Generator[None, None, None]:
        with self._meta:
            lk = self._locks[key]
        lk.acquire()
        try:
            yield
        finally:
            lk.release()


# ═══════════════════════════════════════════════════════════════════
# Heartbeat Scheduler
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Heartbeat:
    name: str
    schedule: str       # e.g. "every 10 minutes", "daily at 09:00"
    prompt: str         # user-style prompt sent to the agent
    agent: str = "main"


class HeartbeatScheduler:
    def __init__(self) -> None:
        self._heartbeats: list[Heartbeat] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def add(self, hb: Heartbeat, callback: Callable[[Heartbeat], None]) -> None:
        import schedule as sched_lib
        self._heartbeats.append(hb)
        job = _parse_schedule(sched_lib, hb.schedule)
        if job:
            job.do(callback, hb)

    def start(self) -> None:
        import schedule as sched_lib
        self._stop.clear()

        def _run():
            while not self._stop.is_set():
                sched_lib.run_pending()
                self._stop.wait(1)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def _parse_schedule(sched_lib: Any, expr: str) -> Any:
    """Parse schedule expressions like 'every 10 minutes', 'daily at 09:00'."""
    expr = expr.strip().lower()
    if expr.startswith("every "):
        rest = expr[6:]
        parts = rest.split()
        if len(parts) >= 2:
            try:
                interval = int(parts[0])
                unit = parts[1].rstrip("s")
                return getattr(sched_lib.every(interval), unit + "s", None)
            except (ValueError, AttributeError):
                pass
        if rest.startswith("minute"):
            return sched_lib.every(1).minutes
        if rest.startswith("hour"):
            return sched_lib.every(1).hours
    elif expr.startswith("daily at "):
        time_str = expr[9:].strip()
        return sched_lib.every().day.at(time_str)
    return None


# ═══════════════════════════════════════════════════════════════════
# Multi-Agent Router
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AgentConfig:
    name: str
    model: str
    soul_path: str | None = None
    prefix: str | None = None
    session_prefix: str = "agent:main"
    workspace_path: str | None = None
    _soul: str | None = field(default=None, repr=False)
    _prompt: str | None = field(default=None, repr=False)

    @property
    def soul(self) -> str:
        if self._soul is None:
            self._soul = load_soul(self.soul_path)
        return self._soul

    @property
    def system_prompt(self) -> str:
        if self._prompt is None:
            self._prompt = build_system_prompt(self.soul, self.workspace_path)
        return self._prompt


class AgentRouter:
    def __init__(self, default: AgentConfig, agents: list[AgentConfig] | None = None) -> None:
        self._default = default
        self._prefix_map: dict[str, AgentConfig] = {}
        for a in agents or []:
            if a.prefix:
                self._prefix_map[a.prefix.lower()] = a

    def resolve(self, text: str) -> tuple[AgentConfig, str]:
        lower = text.strip().lower()
        for prefix, agent in self._prefix_map.items():
            if lower.startswith(prefix):
                cleaned = text.strip()[len(prefix):].strip()
                return agent, cleaned or text
        return self._default, text

    @property
    def agent_names(self) -> list[str]:
        names = [self._default.name]
        names.extend(a.name for a in self._prefix_map.values())
        return names


# ═══════════════════════════════════════════════════════════════════
# Agent Loop
# ═══════════════════════════════════════════════════════════════════

OnToolUse = Callable[[str, dict, str], None] | None


def _sanitize_messages(msgs: list[dict]) -> list[dict]:
    """Strip trailing orphaned assistant tool-call messages."""
    while msgs and msgs[-1].get("role") == "assistant" and msgs[-1].get("tool_calls"):
        msgs.pop()
    return msgs


def run_agent_turn(
    client: Any,
    model: str,
    system_prompt: str,
    session_key: str,
    user_text: str,
    registry: ToolRegistry,
    max_turns: int = MAX_TOOL_TURNS,
    on_tool_use: OnToolUse = None,
) -> str:
    """Run one full agent turn: load → LLM loop → save."""
    messages = _sanitize_messages(load_session(session_key))

    # Compact if over threshold
    if estimate_tokens(messages) >= COMPACTION_THRESHOLD:
        messages = compact(messages, client, model)
        save_session(session_key, messages)

    user_msg = {"role": "user", "content": user_text}
    messages.append(user_msg)
    append_msg(session_key, user_msg)

    api_msgs = [{"role": "system", "content": system_prompt}] + messages
    tools = registry.get_schemas()

    for _ in range(max_turns):
        kwargs: dict[str, Any] = {"model": model, "messages": api_msgs, "max_tokens": 4096}
        if tools:
            kwargs["tools"] = tools

        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        # Serialize assistant message
        ser: dict[str, Any] = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            ser["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]

        # Anthropic via Portkey returns "tool_use", OpenAI returns "tool_calls"
        has_tools = choice.finish_reason in ("tool_calls", "tool_use") and msg.tool_calls
        if not has_tools:
            messages.append(ser)
            append_msg(session_key, ser)
            return msg.content or ""

        # Execute tools, then persist atomically
        tool_results: list[dict] = []
        for tc in msg.tool_calls:
            try:
                inp = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                inp = {}
            result = registry.execute(tc.function.name, inp)
            if on_tool_use:
                on_tool_use(tc.function.name, inp, result)
            tool_results.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

        # Persist assistant + tool results together
        messages.append(ser)
        append_msg(session_key, ser)
        api_msgs.append(ser)
        for tr in tool_results:
            messages.append(tr)
            append_msg(session_key, tr)
            api_msgs.append(tr)

    return "(max tool turns reached)"


# ═══════════════════════════════════════════════════════════════════
# REPL
# ═══════════════════════════════════════════════════════════════════

def _approval_prompt(command: str) -> bool:
    print(f"\n  ⚠️  Command: {command}")
    try:
        return input("  Allow? (y/n): ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _on_tool_use(name: str, inp: dict, result: str) -> None:
    preview = json.dumps(inp)
    if len(preview) > 100:
        preview = preview[:97] + "..."
    print(f"  🔧 {name}: {preview}")
    print(f"     → {str(result)[:150]}")


def main() -> None:
    ensure_dirs()
    client = get_client()
    memory = MemoryStore(MEMORY_DIR)
    pm = PermissionManager(APPROVALS_FILE, callback=_approval_prompt)
    queue = CommandQueue()

    # Build tool registry
    registry = ToolRegistry()
    registry.register(make_shell_tool(pm))
    registry.register(make_read_file_tool())
    registry.register(make_write_file_tool())
    for t in make_memory_tools(memory):
        registry.register(t)
    registry.register(make_web_search_tool())

    # Multi-agent: Jarvis (default) + Scout (/research)
    jarvis = AgentConfig(name="Jarvis", model=DEFAULT_MODEL, soul_path=SOUL_PATH,
                         session_prefix="agent:main", workspace_path=WORKSPACE_DIR)
    scout_soul = os.path.join(WORKSPACE_DIR, "SCOUT.md")
    scout = AgentConfig(name="Scout", model=DEFAULT_MODEL,
                        soul_path=scout_soul if os.path.exists(scout_soul) else None,
                        prefix="/research", session_prefix="agent:research",
                        workspace_path=WORKSPACE_DIR)
    router = AgentRouter(default=jarvis, agents=[scout])

    user_id = "repl"

    print("Mini OpenClaw (single-file)")
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Workspace: {WORKSPACE_DIR}")
    print(f"  Agents: {', '.join(router.agent_names)}")
    print(f"  Tools: {', '.join(registry.tool_names)}")
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

        agent, cleaned = router.resolve(user_input)
        session_key = f"{agent.session_prefix}:repl:{user_id}"

        try:
            with queue.lock(session_key):
                response = run_agent_turn(
                    client=client,
                    model=agent.model,
                    system_prompt=agent.system_prompt,
                    session_key=session_key,
                    user_text=cleaned,
                    registry=registry,
                    on_tool_use=_on_tool_use,
                )
            label = agent.name if agent.name != "Jarvis" else "🤖"
            print(f"\n{label} {response}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    main()
