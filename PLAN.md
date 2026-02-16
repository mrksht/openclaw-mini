# OpenClaw Clone — Implementation Plan

## Overview

Build a **mini OpenClaw**: a persistent AI assistant with memory, tools, multi-channel support, scheduled tasks, and multi-agent routing. Built incrementally from first principles in Python.

**Final deliverable:** A production-quality CLI + multi-channel AI assistant in ~1500 lines of Python, fully tested, modular, and extensible.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      Gateway                            │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌───────┐  │
│  │ Telegram  │  │ Discord  │  │ HTTP API │  │  REPL  │  │
│  │ Adapter   │  │ Adapter  │  │ Adapter  │  │Adapter │  │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬───┘  │
│        └──────────────┴─────────────┴────────────┘      │
│                         │                               │
│              ┌──────────▼──────────┐                    │
│              │   Command Queue     │                    │
│              │  (per-session lock) │                    │
│              └──────────┬──────────┘                    │
│                         │                               │
│              ┌──────────▼──────────┐                    │
│              │   Agent Router      │                    │
│              │  (multi-agent)      │                    │
│              └──────────┬──────────┘                    │
│                         │                               │
│              ┌──────────▼──────────┐                    │
│              │   Agent Loop        │                    │
│              │  LLM ↔ Tools cycle  │                    │
│              └──────────┬──────────┘                    │
│                         │                               │
│        ┌────────────────┼────────────────┐              │
│        ▼                ▼                ▼              │
│  ┌──────────┐   ┌──────────────┐  ┌──────────┐         │
│  │ Sessions │   │    Tools     │  │  Memory  │         │
│  │ (JSONL)  │   │  Executor    │  │  Store   │         │
│  └──────────┘   └──────────────┘  └──────────┘         │
│                         │                               │
│              ┌──────────▼──────────┐                    │
│              │   Permissions       │                    │
│              │   (allowlist)       │                    │
│              └─────────────────────┘                    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Heartbeat Scheduler                │    │
│  │  (cron jobs → injects messages into queue)      │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
openclaw-clone/
├── PLAN.md                      # This file
├── README.md                    # Usage docs
├── pyproject.toml               # Project config + dependencies
├── .env.example                 # Template for API keys
├── .gitignore
│
├── src/
│   └── openclaw/
│       ├── __init__.py
│       ├── main.py              # Entry point (REPL + channel startup)
│       ├── config.py            # Configuration loading
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── loop.py          # Core agent loop (LLM ↔ tools cycle)
│       │   ├── router.py        # Multi-agent routing
│       │   └── soul.py          # SOUL.md loading + system prompt builder
│       │
│       ├── session/
│       │   ├── __init__.py
│       │   ├── store.py         # JSONL session persistence
│       │   └── compaction.py    # Context window compaction
│       │
│       ├── memory/
│       │   ├── __init__.py
│       │   └── store.py         # Long-term file-based memory (save + search)
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py      # Tool registration + schema definitions
│       │   ├── executor.py      # Tool dispatch + execution
│       │   ├── shell.py         # run_command tool
│       │   ├── filesystem.py    # read_file, write_file tools
│       │   ├── memory_tools.py  # save_memory, memory_search tools
│       │   └── web.py           # web_search tool (stub/real)
│       │
│       ├── permissions/
│       │   ├── __init__.py
│       │   └── manager.py       # Command approval + allowlist
│       │
│       ├── queue/
│       │   ├── __init__.py
│       │   └── command_queue.py  # Per-session locking
│       │
│       ├── channels/
│       │   ├── __init__.py
│       │   ├── base.py          # Abstract channel adapter interface
│       │   ├── repl.py          # Local REPL channel
│       │   ├── telegram.py      # Telegram adapter
│       │   ├── discord_ch.py    # Discord adapter
│       │   └── http_api.py      # HTTP REST API adapter
│       │
│       └── heartbeat/
│           ├── __init__.py
│           └── scheduler.py     # Cron/scheduled task runner
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── test_session_store.py
│   ├── test_compaction.py
│   ├── test_memory.py
│   ├── test_permissions.py
│   ├── test_tools.py
│   ├── test_agent_loop.py
│   ├── test_router.py
│   ├── test_command_queue.py
│   └── test_heartbeat.py
│
├── workspace/                   # Default agent workspace (gitignored)
│   └── SOUL.md                  # Default personality file
│
└── scripts/
    └── mini-openclaw.py         # Single-file version (from blog post)
```

---

## Phases

### Phase 0: Project Scaffolding
**Goal:** Set up Python project with tooling, dependencies, and structure.

| Task | Details |
|------|---------|
| 0.1 | Create `pyproject.toml` with dependencies: `anthropic`, `python-telegram-bot`, `discord.py`, `flask`, `schedule`, `python-dotenv` |
| 0.2 | Create `.env.example` with `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN` |
| 0.3 | Create `.gitignore` (Python defaults + `workspace/` + `.env`) |
| 0.4 | Create directory structure with `__init__.py` files |
| 0.5 | Create `README.md` with project overview and setup instructions |
| 0.6 | Verify `uv sync` installs cleanly |

**Exit criteria:** `uv run python -c "import openclaw"` works.

---

### Phase 1: Session Store (JSONL Persistence)
**Goal:** Crash-safe conversation storage. Each session = one JSONL file.

| Task | Details |
|------|---------|
| 1.1 | Implement `SessionStore` class in `src/openclaw/session/store.py` |
| 1.2 | Methods: `load(session_key) → list[dict]`, `append(session_key, message)`, `save(session_key, messages)` |
| 1.3 | Session key → filename mapping (sanitize `:` and `/`) |
| 1.4 | Handle corrupted lines gracefully (skip bad JSON) |
| 1.5 | Write unit tests: create, append, load, crash recovery, bad JSON |

**Key design decisions:**
- JSONL (one JSON object per line), not a single JSON array — append-only is crash-safe
- Session keys like `agent:main:user:12345` map to `agent_main_user_12345.jsonl`
- Store directory configurable, defaults to `~/.mini-openclaw/sessions/`

**Exit criteria:** Tests pass. Can create, append, reload sessions across process restarts.

---

### Phase 2: SOUL — Agent Personality
**Goal:** Load a markdown personality file and inject it as the system prompt.

| Task | Details |
|------|---------|
| 2.1 | Implement `load_soul(path) → str` in `src/openclaw/agent/soul.py` |
| 2.2 | Create default `workspace/SOUL.md` with a solid default personality |
| 2.3 | Implement `build_system_prompt(soul, context)` that injects dynamic context (workspace path, current date, available tools) |
| 2.4 | Write tests: loading, missing file fallback, prompt building |

**Key design decisions:**
- SOUL.md is plain markdown — easy to edit, version, and share
- Dynamic context (date, workspace path) gets appended at runtime
- If SOUL.md is missing, use a sensible built-in default

**Exit criteria:** `load_soul("workspace/SOUL.md")` returns the personality string.

---

### Phase 3: Tool System
**Goal:** Extensible tool registry with schema definitions and execution dispatch.

| Task | Details |
|------|---------|
| 3.1 | Define `Tool` dataclass in `src/openclaw/tools/registry.py`: name, description, input_schema, handler function |
| 3.2 | Implement `ToolRegistry` class: `register(tool)`, `get_schemas() → list[dict]`, `execute(name, input) → str` |
| 3.3 | Implement `run_command` tool in `src/openclaw/tools/shell.py` |
| 3.4 | Implement `read_file`, `write_file` tools in `src/openclaw/tools/filesystem.py` |
| 3.5 | Implement `save_memory`, `memory_search` tools in `src/openclaw/tools/memory_tools.py` |
| 3.6 | Implement `web_search` stub tool in `src/openclaw/tools/web.py` |
| 3.7 | Write tests: registration, schema generation, execution, error handling |

**Key design decisions:**
- Tools are registered via a registry, not hardcoded — easy to add new ones
- Each tool is a function `(input: dict) → str` — simple, testable
- Tool output is always a string (simplifies serialization)
- Tools handle their own errors and return error messages (never raise to agent loop)

**Exit criteria:** `registry.execute("read_file", {"path": "/tmp/test.txt"})` returns file contents.

---

### Phase 4: Permission Controls
**Goal:** Safety layer for shell commands. Approve once, remember forever.

| Task | Details |
|------|---------|
| 4.1 | Implement `PermissionManager` class in `src/openclaw/permissions/manager.py` |
| 4.2 | Define safe command allowlist (ls, cat, git, python, etc.) |
| 4.3 | Implement `check(command) → "safe" | "approved" | "needs_approval"` |
| 4.4 | Implement persistent approval storage (JSON file) |
| 4.5 | Support approval callback (prompt user interactively or auto-deny) |
| 4.6 | Wire into `run_command` tool |
| 4.7 | Write tests: safe commands, approvals, persistence, denial |

**Key design decisions:**
- Allowlist-based: known-safe commands auto-execute, everything else asks
- Approvals persist to `exec-approvals.json` — no re-asking
- Approval callback is injectable: REPL prompts interactively, Telegram sends a message
- Base command is extracted for safety check (`git push` → `git` is safe)

**Exit criteria:** `ls` runs without prompt. `curl ... | sh` requires approval.

---

### Phase 5: Agent Loop
**Goal:** The core LLM ↔ tool execution cycle. Call the model, execute tools, feed results back, repeat until done.

| Task | Details |
|------|---------|
| 5.1 | Implement `run_agent_turn()` in `src/openclaw/agent/loop.py` |
| 5.2 | Handle response content serialization (text blocks + tool_use blocks) |
| 5.3 | Process tool calls: execute each, build tool_result messages |
| 5.4 | Loop until `stop_reason == "end_turn"` or max iterations (20) |
| 5.5 | Integrate session store (load, append each message, save) |
| 5.6 | Integrate tool registry for execution |
| 5.7 | Write tests with mocked LLM responses: text-only, single tool call, multi-tool chain, max iterations |

**Key design decisions:**
- Agent loop is channel-agnostic — takes a session key and user text, returns response text
- Each message (user, assistant, tool_result) is appended individually for crash safety
- Max 20 tool-use iterations to prevent infinite loops
- Content blocks are serialized to plain dicts for JSONL storage

**Exit criteria:** Agent can have a multi-turn conversation with tool use, persisted to disk.

---

### Phase 6: REPL Channel
**Goal:** First channel — interactive terminal for testing everything.

| Task | Details |
|------|---------|
| 6.1 | Implement `ReplChannel` in `src/openclaw/channels/repl.py` |
| 6.2 | Support commands: `/new` (reset session), `/quit`, `/research <query>` |
| 6.3 | Pretty-print tool usage during agent turns |
| 6.4 | Implement `main()` entry point in `src/openclaw/main.py` |
| 6.5 | Wire together: config → session store → tool registry → permission manager → agent loop → REPL |

**Key design decisions:**
- REPL is the primary development/testing interface
- All dependencies are injected (session store, tool registry, etc.)
- `/new` creates a new session key with a timestamp suffix

**Exit criteria:** Can run `uv run python -m openclaw` and have a full conversation with tools, memory, and permissions.

---

### Phase 7: Context Compaction
**Goal:** Automatically summarize old messages when approaching the context window limit.

| Task | Details |
|------|---------|
| 7.1 | Implement `estimate_tokens(messages) → int` in `src/openclaw/session/compaction.py` |
| 7.2 | Implement `compact(session_key, messages, llm_client) → messages` |
| 7.3 | Split messages at midpoint, summarize old half, prepend summary to recent half |
| 7.4 | Save compacted session to disk |
| 7.5 | Integrate into agent loop (compact before each turn) |
| 7.6 | Write tests with mock LLM: threshold detection, summary injection, session overwrite |

**Key design decisions:**
- Token estimation: `len(json.dumps(msg)) // 4` — rough but effective
- Threshold: 100k tokens (80% of 128k window) — leaves room for response
- Compaction is idempotent: if already under threshold, no-op
- Summary is injected as a `[Conversation summary]` user message

**Exit criteria:** A session with 200k estimated tokens gets compacted to ~60k.

---

### Phase 8: Long-Term Memory
**Goal:** File-based memory that survives session resets, accessible to all agents.

| Task | Details |
|------|---------|
| 8.1 | Implement `MemoryStore` class in `src/openclaw/memory/store.py` |
| 8.2 | `save(key, content)` — write markdown file to memory directory |
| 8.3 | `search(query) → str` — keyword search across all memory files |
| 8.4 | `list() → list[str]` — list all memory keys |
| 8.5 | `delete(key)` — remove a memory file |
| 8.6 | Wire into memory tools (save_memory, memory_search) |
| 8.7 | Write tests: save, search, list, delete, no-match, multi-file |

**Key design decisions:**
- One markdown file per memory key: `memory/user-preferences.md`
- Keyword search: split query into words, match any word in file content (case-insensitive)
- Memory directory is shared across all agents — agents collaborate via shared files
- Future: could add vector search with embeddings

**Exit criteria:** Save a memory in one session, reset, search for it in a new session — found.

---

### Phase 9: Command Queue (Concurrency)
**Goal:** Per-session locking to prevent race conditions from concurrent messages.

| Task | Details |
|------|---------|
| 9.1 | Implement `CommandQueue` class in `src/openclaw/queue/command_queue.py` |
| 9.2 | Per-session `threading.Lock` via `defaultdict(Lock)` |
| 9.3 | Context manager interface: `with queue.lock(session_key):` |
| 9.4 | Integrate into agent loop |
| 9.5 | Write tests: sequential execution, cross-session parallelism |

**Key design decisions:**
- Simple `defaultdict(threading.Lock)` — no external dependencies
- Different sessions can process simultaneously
- Same session queues messages — FIFO ordering

**Exit criteria:** Two concurrent messages to the same session execute sequentially without corruption.

---

### Phase 10: Heartbeat Scheduler
**Goal:** Scheduled agent execution — recurring tasks that trigger without human input.

| Task | Details |
|------|---------|
| 10.1 | Implement `HeartbeatScheduler` class in `src/openclaw/heartbeat/scheduler.py` |
| 10.2 | Config-driven heartbeat definitions: name, schedule, agent, prompt |
| 10.3 | Each heartbeat uses its own isolated session key (`cron:<name>`) |
| 10.4 | Background thread runs `schedule.run_pending()` every 60s |
| 10.5 | Optional: route heartbeat output to a channel (e.g., send to Telegram) |
| 10.6 | Write tests: scheduling, execution, isolation |

**Key design decisions:**
- Heartbeats use isolated session keys so they don't pollute main conversations
- Schedule format: `schedule` library syntax (human-readable)
- Heartbeat output is logged; optionally forwarded to a notification channel
- Scheduler runs in a daemon thread — dies with the main process

**Exit criteria:** A heartbeat fires every minute (for testing), runs the agent, and logs the response.

---

### Phase 11: Multi-Agent Routing
**Goal:** Multiple agent configurations with prefix-based routing.

| Task | Details |
|------|---------|
| 11.1 | Implement `AgentRouter` class in `src/openclaw/agent/router.py` |
| 11.2 | Config-driven agent definitions: name, model, SOUL, session_prefix |
| 11.3 | Prefix routing: `/research <query>` → researcher agent |
| 11.4 | Default agent for unmatched messages |
| 11.5 | Each agent gets its own session prefix |
| 11.6 | Shared memory directory across agents |
| 11.7 | Write tests: routing, fallback, session isolation |

**Key design decisions:**
- Agents are config objects, not separate processes
- Routing is prefix-based: `/research`, `/code`, etc.
- All agents share the same memory store — they collaborate via files
- Each agent has its own session history (different session prefix)

**Exit criteria:** `/research <query>` routes to Scout, normal messages to Jarvis. Both can access shared memory.

---

### Phase 12: Gateway — Multi-Channel Support
**Goal:** Abstract channel interface + Telegram and HTTP adapters.

| Task | Details |
|------|---------|
| 12.1 | Define `ChannelAdapter` abstract base class in `src/openclaw/channels/base.py` |
| 12.2 | Methods: `start()`, `stop()`, `send_message(session_key, text)` |
| 12.3 | Implement `TelegramChannel` in `src/openclaw/channels/telegram.py` |
| 12.4 | Implement `HttpApiChannel` in `src/openclaw/channels/http_api.py` (Flask) |
| 12.5 | Implement `DiscordChannel` in `src/openclaw/channels/discord_ch.py` |
| 12.6 | Update `main.py` to start channels based on config (which tokens are present) |
| 12.7 | Prove shared sessions: message on Telegram, query via HTTP, same memory |
| 12.8 | Write integration tests |

**Key design decisions:**
- Each channel normalizes messages into `(session_key, user_text)` and calls `run_agent_turn()`
- Session key construction: `agent:<agent_id>:<channel>:<user_id>`
- Channels start conditionally based on which env vars / config are present
- Channel adapters run in their own threads

**Exit criteria:** Send "My name is Nader" on Telegram, ask "What's my name?" via HTTP API — bot remembers.

---

### Phase 13: Configuration System
**Goal:** Unified config file for agents, channels, heartbeats, and permissions.

| Task | Details |
|------|---------|
| 13.1 | Implement `Config` class in `src/openclaw/config.py` |
| 13.2 | Load from `~/.mini-openclaw/config.json` with sensible defaults |
| 13.3 | Support: workspace path, agent definitions, channel configs, heartbeat schedules |
| 13.4 | Environment variable overrides for secrets |
| 13.5 | Validation on startup |
| 13.6 | Write tests |

**Config schema:**
```json
{
  "workspace": "~/.mini-openclaw",
  "default_model": "claude-sonnet-4-5-20250929",
  "agents": {
    "main": {
      "name": "Jarvis",
      "soul_path": "workspace/SOUL.md",
      "model": "claude-sonnet-4-5-20250929"
    },
    "researcher": {
      "name": "Scout",
      "soul_path": "workspace/SCOUT.md",
      "model": "claude-sonnet-4-5-20250929"
    }
  },
  "channels": {
    "repl": { "enabled": true },
    "telegram": { "enabled": true },
    "http": { "enabled": true, "port": 5000 }
  },
  "heartbeats": [
    {
      "name": "morning-check",
      "schedule": "07:30",
      "agent": "main",
      "prompt": "Good morning! Give me a motivational quote."
    }
  ],
  "permissions": {
    "safe_commands": ["ls", "cat", "git", "python", "node"]
  }
}
```

**Exit criteria:** Bot reads config from file, applies settings, validates on startup.

---

### Phase 14: Single-File Script
**Goal:** Create the blog post's `mini-openclaw.py` — a single runnable file with all features.

| Task | Details |
|------|---------|
| 14.1 | Assemble all features into one `scripts/mini-openclaw.py` |
| 14.2 | ~400 lines, zero config needed, runs with `uv run` |
| 14.3 | Verify all features work: sessions, SOUL, tools, permissions, compaction, memory, queue, cron, multi-agent |

**Exit criteria:** `uv run --with anthropic --with schedule python scripts/mini-openclaw.py` runs a complete assistant.

---

## Implementation Order & Dependencies

```
Phase 0: Scaffolding ──────────────────────────────┐
                                                    │
Phase 1: Session Store ────────────┐                │
                                   │                │
Phase 2: SOUL ─────────────────────┤                │
                                   │                │
Phase 3: Tool System ──────────────┤ (parallel)     │
                                   │                │
Phase 4: Permissions ──────────────┘                │
         │                                          │
         ▼                                          │
Phase 5: Agent Loop ◄──────────────────────────────┘
         │
         ▼
Phase 6: REPL Channel ──── FIRST WORKING VERSION
         │
         ├──► Phase 7: Compaction    ┐
         ├──► Phase 8: Memory        │ (parallel)
         ├──► Phase 9: Command Queue ┘
         │
         ▼
Phase 10: Heartbeats
Phase 11: Multi-Agent Routing
Phase 12: Gateway (Telegram, HTTP, Discord)
Phase 13: Configuration
Phase 14: Single-File Script
```

**Phases 1-4** can be developed in parallel (no dependencies on each other).  
**Phase 5** (Agent Loop) depends on all of 1-4.  
**Phase 6** (REPL) depends on 5 — this is the **first runnable milestone**.  
**Phases 7-9** can be developed in parallel after Phase 6.  
**Phases 10-13** are sequential but each is small.  
**Phase 14** is a cherry-on-top consolidation.

---

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.12+ | Ecosystem, LLM SDK support |
| Package manager | `uv` | Fast, modern, no virtualenv hassle |
| LLM SDK | `anthropic` | Direct Claude API access |
| Telegram | `python-telegram-bot` | Mature, async-native |
| Discord | `discord.py` | Standard choice |
| HTTP API | `flask` | Simple, lightweight |
| Scheduling | `schedule` | Human-readable, zero config |
| Testing | `pytest` | Standard, with `pytest-asyncio` for async |
| Env vars | `python-dotenv` | Load `.env` files |
| Linting | `ruff` | Fast Python linter + formatter |

---

## Key Design Principles

1. **Crash safety first** — JSONL append-only logs, not in-memory state
2. **Channel-agnostic agent** — Agent loop knows nothing about Telegram/Discord/HTTP
3. **Dependency injection** — All components receive their dependencies, never import globals
4. **Tools are data** — Schema + handler function, registered at startup
5. **Config over code** — Agents, channels, heartbeats defined in config, not hardcoded
6. **Shared memory, isolated sessions** — Agents collaborate via files, not direct messaging
7. **Progressive enhancement** — Each phase adds value independently

---

## Estimated Effort

| Phase | Estimated LOC | Effort |
|-------|--------------|--------|
| 0. Scaffolding | 50 | 15 min |
| 1. Session Store | 80 + 60 tests | 30 min |
| 2. SOUL | 40 + 30 tests | 15 min |
| 3. Tool System | 200 + 80 tests | 45 min |
| 4. Permissions | 80 + 50 tests | 30 min |
| 5. Agent Loop | 120 + 80 tests | 45 min |
| 6. REPL Channel | 100 | 30 min |
| 7. Compaction | 60 + 40 tests | 20 min |
| 8. Memory | 70 + 50 tests | 20 min |
| 9. Command Queue | 30 + 30 tests | 15 min |
| 10. Heartbeats | 60 + 30 tests | 20 min |
| 11. Multi-Agent | 60 + 40 tests | 20 min |
| 12. Gateway | 200 + 60 tests | 45 min |
| 13. Configuration | 100 + 40 tests | 30 min |
| 14. Single-File | 400 | 30 min |
| **Total** | **~2100** | **~6 hours** |

---

## Milestones

| Milestone | After Phase | What works |
|-----------|-------------|------------|
| **M1: Chat** | 6 | REPL with memory, tools, permissions, personality |
| **M2: Smart** | 9 | + compaction, long-term memory, concurrency safety |
| **M3: Alive** | 11 | + scheduled tasks, multi-agent routing |
| **M4: Connected** | 13 | + Telegram, Discord, HTTP API, config-driven |
| **M5: Portable** | 14 | + single-file version for sharing |

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Anthropic API key needed for integration tests | Mock LLM responses in unit tests; integration tests gated behind `ANTHROPIC_API_KEY` env var |
| Telegram/Discord tokens needed | Channels start conditionally; REPL always works without tokens |
| Shell execution security | Permission system + timeout + no-root check |
| JSONL corruption on crash | Per-line integrity; skip unparseable lines |
| Context window overflow | Compaction with configurable threshold |
| Rate limiting | Exponential backoff on API calls (future enhancement) |

---

## Ready to Start

Begin with **Phase 0** (scaffolding), then **Phases 1-4** in parallel, then **Phase 5** (agent loop) to reach the first working milestone.
