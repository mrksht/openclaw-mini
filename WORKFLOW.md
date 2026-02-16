# OpenClaw Clone — Complete Architecture & Workflow Guide

## Table of Contents

- [What Is This?](#what-is-this)
- [Tech Stack](#tech-stack)
- [Entry Point](#entry-point)
- [Configuration Layer](#configuration-layer)
- [The Full Request Flow](#the-full-request-flow)
- [Agent Loop — The Core Engine](#agent-loop--the-core-engine)
- [Channels (Gateway Layer)](#channels-gateway-layer)
- [Session Store](#session-store)
- [Context Compaction](#context-compaction)
- [Memory Store](#memory-store)
- [Tool Registry & Tools](#tool-registry--tools)
- [Permissions Manager](#permissions-manager)
- [Agent Router (Multi-Agent)](#agent-router-multi-agent)
- [SOUL (System Prompt)](#soul-system-prompt)
- [Command Queue](#command-queue)
- [Heartbeat Scheduler](#heartbeat-scheduler)
- [Runtime Directory Layout](#runtime-directory-layout)
- [Concrete Example Walkthrough](#concrete-example-walkthrough)

---

## What Is This?

A **persistent AI assistant** built in Python (~1500 LOC) that can:

- Talk to you via **multiple channels** (REPL, HTTP API, Telegram)
- **Execute shell commands** with safety permissions
- **Read/write files** on your machine
- **Remember things** across sessions (long-term memory)
- Run **scheduled background tasks** (heartbeats)
- Route messages to **multiple agents** (Jarvis, Scout)

All powered by LLMs via **Anthropic**, **OpenAI**, or the **Portkey AI gateway** — pick your provider, set one env var, and go.

---

## Tech Stack

| Component       | Technology                                                                 |
| --------------- | -------------------------------------------------------------------------- |
| Language         | Python 3.12+                                                               |
| LLM Provider      | **Anthropic** / **OpenAI** / **Portkey Gateway** (auto-detected, all OpenAI-compatible interface) |
| Env Config       | `python-dotenv`                                                            |
| Scheduling       | `schedule` library                                                         |
| HTTP Channel     | Flask (optional extra)                                                     |
| Telegram Channel | `python-telegram-bot` (optional extra)                                     |
| Build System     | Hatchling                                                                  |
| Testing          | pytest + pytest-asyncio                                                    |
| Linting          | Ruff                                                                       |

---

## Entry Point

**File:** `src/openclaw/main.py`

Registered as the `openclaw` CLI command via `pyproject.toml`:

```toml
[project.scripts]
openclaw = "openclaw.main:main"
```

Running `openclaw` (or `uv run openclaw`) calls `main()`, which does three things:

1. **Parses CLI arguments:**
   - `--config <path>` — path to a JSON config file (optional)
   - `--channel repl|http|telegram` — which channel to start (default: `repl`)

2. **Loads configuration:**
   - With `--config`: loads `AppConfig.from_file(path)` and validates it
   - Without `--config`: creates a default `AppConfig()` (env-var driven)

3. **Launches the selected channel:**
   - `repl` → `run_repl()` — interactive terminal
   - `http` → `_start_http(config)` — Flask web server
   - `telegram` → `_start_telegram(config)` — Telegram bot

```
$ openclaw                          # → REPL mode (default)
$ openclaw --channel http           # → HTTP API on port 5000
$ openclaw --channel telegram       # → Telegram bot (needs TELEGRAM_BOT_TOKEN)
$ openclaw -c config.json --channel http  # → HTTP with custom config
```

---

## Configuration Layer

**File:** `src/openclaw/config.py`

Supports **two modes** of configuration:

### Mode 1: Environment Variables (default)

Reads `.env` from the project root via `python-dotenv`. Module-level constants:

| Constant                    | Env Var              | Default                                                       |
| --------------------------- | -------------------- | ------------------------------------------------------------- |
| `LLM_PROVIDER`              | `LLM_PROVIDER`       | `""` (auto-detected from API keys)                            |
| `ANTHROPIC_API_KEY`         | `ANTHROPIC_API_KEY`  | `""`                                                          |
| `OPENAI_API_KEY`            | `OPENAI_API_KEY`     | `""`                                                          |
| `OPENAI_BASE_URL`           | `OPENAI_BASE_URL`    | `https://api.openai.com/v1`                                   |
| `PORTKEY_API_KEY`           | `PORTKEY_API_KEY`    | `""`                                                          |
| `PORTKEY_BASE_URL`          | `PORTKEY_BASE_URL`   | `https://gateway.ai.cimpress.io/v1`                           |
| `DEFAULT_MODEL`             | `OPENCLAW_MODEL`     | `@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0`     |
| `WORKSPACE_DIR`             | `OPENCLAW_WORKSPACE` | `~/.mini-openclaw`                                            |
| `MAX_TOOL_TURNS`            | —                    | `20`                                                          |
| `COMPACTION_THRESHOLD_TOKENS` | —                  | `100,000`                                                     |

**Provider auto-detection priority:** If `LLM_PROVIDER` is not set, the first API key found wins:
1. `PORTKEY_API_KEY` → Portkey gateway
2. `ANTHROPIC_API_KEY` → Anthropic direct
3. `OPENAI_API_KEY` → OpenAI direct

Derived paths (all under `WORKSPACE_DIR`):
- `SESSIONS_DIR` → `~/.mini-openclaw/sessions`
- `MEMORY_DIR` → `~/.mini-openclaw/memory`
- `APPROVALS_FILE` → `~/.mini-openclaw/exec-approvals.json`
- `SOUL_PATH` → `~/.mini-openclaw/SOUL.md`

### Mode 2: JSON Config File (advanced)

`AppConfig.from_file("config.json")` parses a JSON file with:

```json
{
  "workspace": "~/.mini-openclaw",
  "default_model": "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "agents": {
    "main": { "name": "Jarvis", "soul_path": "...", "model": "..." },
    "research": { "name": "Scout", "prefix": "/research" }
  },
  "channels": {
    "http": { "enabled": true, "port": 5000 }
  },
  "heartbeats": [
    { "name": "morning", "schedule": "every day at 07:30", "prompt": "..." }
  ],
  "permissions": {
    "safe_commands": ["ls", "git", "python"]
  }
}
```

### Key Function: `get_portkey_client()`

Creates an LLM client instance based on the detected provider. Despite the name (kept for backward compatibility), it supports three providers:

| Provider | What it creates | SDK used |
|----------|----------------|----------|
| **Portkey** | `Portkey(api_key, base_url)` | `portkey-ai` (core dependency) |
| **Anthropic** | `OpenAI(api_key, base_url="https://api.anthropic.com/v1/")` | `openai` (optional extra) |
| **OpenAI** | `OpenAI(api_key, base_url)` | `openai` (optional extra) |

All three return a client with the same `client.chat.completions.create(...)` interface, so the rest of the codebase is provider-agnostic.

The helper `_detect_provider()` determines which provider to use:
1. If `LLM_PROVIDER` env var is set → use that
2. Else auto-detect from whichever API key is present (Portkey > Anthropic > OpenAI)

### Key Function: `ensure_workspace()`

Creates `WORKSPACE_DIR`, `SESSIONS_DIR`, and `MEMORY_DIR` if they don't already exist.

---

## The Full Request Flow

Here's the complete journey of a user message through the system:

```
 ┌──────────────────────────────────────────────────────────────────┐
 │  USER INPUT: "What files are in /tmp?"                          │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  STEP 1 — CHANNEL (REPL / HTTP / Telegram)                     │
 │  Normalizes input into: (user_text, user_id, channel_name)     │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  STEP 2 — COMMAND QUEUE                                        │
 │  CommandQueue.lock(session_key)                                 │
 │  Acquires per-session lock to prevent concurrent turns          │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  STEP 3 — AGENT ROUTER                                         │
 │  AgentRouter.resolve(user_text)                                 │
 │  Checks if message starts with a prefix (e.g. "/research")     │
 │  Returns: (AgentConfig, cleaned_text)                          │
 │  Builds session_key: "{session_prefix}:{channel}:{user_id}"    │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  STEP 4 — SOUL LOADING                                         │
 │  load_soul(soul_path) → reads SOUL.md markdown                 │
 │  build_system_prompt(soul, workspace, date) → system prompt    │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  STEP 5 — AGENT LOOP (run_agent_turn)                          │
 │  The core LLM ↔ Tool execution cycle                           │
 │  See detailed breakdown below                                   │
 └──────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  RESPONSE returned to channel → displayed to user              │
 └──────────────────────────────────────────────────────────────────┘
```

---

## Agent Loop — The Core Engine

**File:** `src/openclaw/agent/loop.py`  
**Function:** `run_agent_turn()`

This is the heart of the system. It manages the LLM ↔ tool execution cycle.

### Step-by-Step Breakdown

```
run_agent_turn(client, model, system_prompt, session_key, user_text, ...)
│
├── 1. LOAD HISTORY
│     SessionStore.load(session_key) → list of previous messages from JSONL file
│
├── 2. SANITIZE
│     _sanitize_loaded_messages() → removes orphaned tool-call messages
│     (handles crashes where assistant requested tools but results were never saved)
│
├── 3. CHECK COMPACTION
│     estimate_tokens(messages) → rough count (chars / 4)
│     if > 100,000 tokens → compact() — summarize old messages (see Compaction section)
│
├── 4. APPEND USER MESSAGE
│     Add {"role": "user", "content": user_text} to history
│     SessionStore.append() → persist to JSONL file immediately
│
└── 5. LLM LOOP (up to 20 iterations)
      │
      ├── Build API payload:
      │     messages = [{"role": "system", "content": system_prompt}] + conversation_history
      │     tools = tool_registry.get_schemas()  (OpenAI function-calling format)
      │
      ├── Call LLM:
      │     client.chat.completions.create(model=..., messages=..., tools=..., max_tokens=4096)
      │
      ├── If response has NO tool calls:
      │     → Persist assistant message to SessionStore
      │     → RETURN the text response (loop ends)
      │
      └── If response HAS tool calls:
            │
            ├── For each tool_call in response:
            │     ├── Parse: tool_name, tool_arguments (JSON)
            │     ├── Execute: tool_registry.execute(name, args) → result string
            │     ├── Callback: on_tool_use(name, args, result) → prints to terminal
            │     └── Build: {"role": "tool", "tool_call_id": "...", "content": result}
            │
            ├── ATOMIC PERSIST: save assistant message + all tool results together
            │   (prevents orphaned tool-call messages on crash)
            │
            └── Continue loop → LLM sees tool results and decides next action
```

### Why Atomic Persistence Matters

If the system crashed between saving the assistant's tool-call message and saving the tool results, the next load would have a broken conversation (assistant asking for tools with no answers). The loop saves both atomically, and `_sanitize_loaded_messages()` cleans up any edge cases on load.

### Exit Conditions

| Condition | What Happens |
|-----------|--------------|
| LLM returns text (no tool calls) | Normal exit — return response |
| 20 tool iterations reached | Safety exit — returns `"(max tool turns reached)"` |

---

## Channels (Gateway Layer)

All channels implement the `ChannelAdapter` abstract base class:

**File:** `src/openclaw/channels/base.py`

```python
class ChannelAdapter(ABC):
    @property
    def name(self) -> str: ...       # "repl", "http", "telegram"
    def start(self) -> None: ...     # Start the channel
    def stop(self) -> None: ...      # Gracefully stop
```

### REPL Channel

**File:** `src/openclaw/channels/repl.py`

The default interactive terminal interface.

**What `run_repl()` does:**

1. **Setup workspace** — creates dirs, copies default `SOUL.md` if missing
2. **Initialize all components:**
   - `get_portkey_client()` → LLM client (Anthropic, OpenAI, or Portkey — auto-detected)
   - `SessionStore(SESSIONS_DIR)` → session persistence
   - `MemoryStore(MEMORY_DIR)` → long-term memory
   - `PermissionManager(APPROVALS_FILE, approval_callback=_approval_prompt)` → with interactive y/n prompt
   - `ToolRegistry` → registers all 6 tools
   - `CommandQueue()` → per-session locking
3. **Set up multi-agent router:**
   - Default agent: **Jarvis** (no prefix)
   - Research agent: **Scout** (`/research` prefix)
4. **Enter input loop:**
   - Read user input via `input("You: ")`
   - Handle commands: `/quit`, `/new` (reset session), `/research <query>`
   - Route message through `AgentRouter` → `CommandQueue` → `run_agent_turn()`
   - Print response with agent label

**Special commands:**
- `/new` — resets the session by changing the user_id suffix
- `/quit` / `/exit` / `/q` — exits the REPL
- `/research <query>` — routes to the Scout agent

### HTTP Channel

**File:** `src/openclaw/channels/http_api.py`

Flask-based REST API. Runs in a daemon thread.

**Endpoints:**

| Method | Path        | Description                                    |
| ------ | ----------- | ---------------------------------------------- |
| `POST` | `/chat`     | Send `{"message": "...", "user_id": "..."}` → `{"response": "..."}` |
| `GET`  | `/health`   | Returns `{"status": "ok", "agents": [...]}` |
| `GET`  | `/sessions` | Lists all session filenames |

**Request flow:** `POST /chat` → parse JSON → resolve agent → acquire session lock → run agent turn → return JSON response.

### Telegram Channel

**File:** `src/openclaw/channels/telegram.py`

Uses `python-telegram-bot` library with **long-polling** (no webhook needed).

**Handlers:**
- `/start` — welcome message with agent names and available commands
- `/new` — reset session (changes session suffix in `user_data`)
- `/research <query>` — explicit command handler for the research agent
- Regular text messages — routed through the agent router

**Features:**
- Shows "typing..." indicator while the LLM responds
- Splits responses longer than 4096 chars (Telegram's limit) into multiple messages
- Logs all activity to terminal for operator visibility
- Each Telegram chat gets its own isolated session key

---

## Session Store

**File:** `src/openclaw/session/store.py`

Persists conversation history as **JSONL files** (one JSON object per line).

### How It Works

```
Session Key: "agent:main:repl:repl"
     ↓ sanitize
Filename: "agent_main_repl_repl.jsonl"
     ↓
Location: ~/.mini-openclaw/sessions/agent_main_repl_repl.jsonl
```

**File format** (each line is a JSON message):
```jsonl
{"role": "user", "content": "What files are in /tmp?"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "run_command", "arguments": "{\"command\": \"ls /tmp\"}"}}]}
{"role": "tool", "tool_call_id": "call_123", "content": "foo.txt bar.txt"}
{"role": "assistant", "content": "The files in /tmp are: foo.txt and bar.txt"}
```

### Key Methods

| Method           | What It Does                                                       |
| ---------------- | ------------------------------------------------------------------ |
| `load(key)`      | Read all messages from JSONL file. Returns `[]` if file doesn't exist. Skips corrupted lines. |
| `append(key, msg)` | Append one message line (crash-safe — append-only write) |
| `save(key, msgs)` | Overwrite entire file (used after compaction) |
| `list_sessions()` | List all session filenames (without `.jsonl` extension) |
| `delete(key)`    | Delete a session file |
| `message_count(key)` | Count messages without loading into memory |

### Crash Safety

- **Append-only writes** → at most one line lost on crash
- Corrupted lines (partial JSON from crash) are silently skipped on load
- Orphaned tool-call messages cleaned up by the agent loop's sanitizer

---

## Context Compaction

**File:** `src/openclaw/session/compaction.py`

Prevents conversations from exceeding the LLM's context window.

### How It Works

```
Messages in session → estimate_tokens() → chars / 4
     │
     ├── Under 100K tokens → no-op, return messages as-is
     │
     └── Over 100K tokens → COMPACT:
           │
           ├── Split messages at midpoint (on a user-message boundary)
           │   ├── OLD HALF: first ~50% of messages
           │   └── RECENT HALF: last ~50% of messages
           │
           ├── Format OLD HALF into readable text
           │
           ├── Ask LLM to summarize:
           │   "Summarize the following conversation concisely.
           │    Preserve all important facts, decisions, user preferences,
           │    file paths, variable names, and action outcomes."
           │
           ├── Replace OLD HALF with one summary message:
           │   {"role": "user", "content": "[Conversation summary of N messages]\n\n• ..."}
           │
           └── Return: [summary_message] + RECENT HALF
               (much shorter — fits in context window)
```

### Smart Splitting

The split tries to land on a **user-message boundary** to avoid breaking an assistant→tool→result sequence in the middle. It searches forward from midpoint, then backward, then falls back to exact midpoint.

---

## Memory Store

**File:** `src/openclaw/memory/store.py`

Long-term file-based memory that **persists across session resets** and is **shared across all agents**.

### Storage Format

Each memory is a **markdown file**:
```
~/.mini-openclaw/memory/
├── user-preferences.md      ← key: "user-preferences"
├── project-notes.md         ← key: "project-notes"
└── meeting-summary-jan.md   ← key: "meeting-summary-jan"
```

### Key Methods

| Method          | What It Does                                              |
| --------------- | --------------------------------------------------------- |
| `save(key, content)` | Write/overwrite a markdown memory file |
| `load(key)`     | Read a specific memory by key. Returns `None` if not found. |
| `search(query)` | Keyword search (case-insensitive) across all memory files. Splits query into words, matches any word. |
| `list_keys()`   | List all memory keys (filenames without `.md`) |
| `delete(key)`   | Delete a memory file |

### How the Agent Uses Memory

The agent has two tools that bridge to this store:
- **`save_memory`** — the agent calls this when it encounters important information (user preferences, project details, key decisions)
- **`memory_search`** — the agent calls this to recall information from previous sessions

The SOUL instructs the agent: *"Use `memory_search` at the start of conversations to recall context from previous sessions."*

---

## Tool Registry & Tools

**File:** `src/openclaw/tools/registry.py`

### Tool Data Model

Each tool is a dataclass:
```python
@dataclass
class Tool:
    name: str                           # Unique ID (e.g. "run_command")
    description: str                    # For the LLM to understand when to use it
    input_schema: dict[str, Any]        # JSON Schema for parameters
    handler: Callable[[dict], str]      # The actual execution function
```

### Registry Operations

| Method                  | What It Does                                                 |
| ----------------------- | ------------------------------------------------------------ |
| `register(tool)`        | Add a tool. Raises `ValueError` on duplicate names. |
| `get_schemas()`         | Returns all tools in **OpenAI function-calling format** for the API |
| `execute(name, input)`  | Dispatches to the tool's handler. Catches exceptions — never raises. |
| `tool_names`            | List of registered tool names |

### The 6 Registered Tools

#### 1. `run_command` — Shell Execution
**File:** `src/openclaw/tools/shell.py`

```
Input:  {"command": "ls -la /tmp"}
Output: "total 48\ndrwxrwxrwt  12 root  wheel  384 Feb 16 10:00 .\n..."
```

- Runs via `subprocess.run()` with `shell=True`
- **30-second timeout** — prevents hanging
- **Permission-checked** — goes through `PermissionManager` first
- Captures both stdout and stderr

#### 2. `read_file` — File Reading
**File:** `src/openclaw/tools/filesystem.py`

```
Input:  {"path": "/Users/me/project/README.md"}
Output: "# My Project\n\nThis is a readme..."
```

- Max read size: **50,000 characters** (truncates with notice)
- Handles: `FileNotFoundError`, `IsADirectoryError`

#### 3. `write_file` — File Writing
**File:** `src/openclaw/tools/filesystem.py`

```
Input:  {"path": "/tmp/hello.txt", "content": "Hello, world!"}
Output: "Wrote 13 characters to /tmp/hello.txt"
```

- Creates parent directories automatically (`os.makedirs`)

#### 4. `save_memory` — Long-Term Memory Save
**File:** `src/openclaw/tools/memory_tools.py`

```
Input:  {"key": "user-preferences", "content": "Prefers dark mode. Uses Python 3.12."}
Output: "Saved to memory: user-preferences"
```

#### 5. `memory_search` — Long-Term Memory Search
**File:** `src/openclaw/tools/memory_tools.py`

```
Input:  {"query": "preferences"}
Output: "--- user-preferences ---\nPrefers dark mode. Uses Python 3.12."
```

#### 6. `web_search` — Web Search (stub)
**File:** `src/openclaw/tools/web.py`

```
Input:  {"query": "Python 3.13 release date"}
Output: "[Web search stub] Results for: Python 3.13 release date\nNote: Connect a real search API..."
```

Currently a placeholder. To enable real search, connect SerpAPI, Brave Search, or similar.

---

## Permissions Manager

**File:** `src/openclaw/permissions/manager.py`

Safety layer for shell command execution. Prevents the AI from running dangerous commands without your explicit approval.

### Decision Flow

```
Command arrives: "rm -rf /important"
     │
     ▼
PermissionManager.check(command)
     │
     ├── Is base command in SAFE SET?
     │   (ls, cat, git, python, grep, find, echo, etc.)
     │   → YES → return "safe" → auto-execute
     │
     ├── Was this EXACT command previously approved?
     │   (check exec-approvals.json)
     │   → YES → return "approved" → auto-execute
     │
     └── Neither?
         → return "needs_approval"
              │
              ▼
         PermissionManager.request_approval(command)
              │
              ├── REPL: prints "⚠️ Command: rm -rf /important"
              │          prompts "Allow? (y/n): "
              │
              ├── User says YES → save to "allowed" in JSON → execute
              └── User says NO  → save to "denied" in JSON → return "Permission denied"
```

### Safe Commands (default set)

```
ls, cat, head, tail, wc, date, whoami, echo, pwd, which,
git, python, python3, node, npm, npx, uv, pip, find, grep,
sort, uniq, tr, cut, env
```

### Persistent Approvals

Stored in `~/.mini-openclaw/exec-approvals.json`:
```json
{
  "allowed": ["docker ps", "brew install jq"],
  "denied": ["rm -rf /"]
}
```

Once approved, you're **never asked again** for the same exact command.

---

## Agent Router (Multi-Agent)

**File:** `src/openclaw/agent/router.py`

Routes messages to different agents based on **prefix commands**.

### Registered Agents

| Agent      | Prefix       | Session Prefix   | SOUL File            |
| ---------- | ------------ | ---------------- | -------------------- |
| **Jarvis** | *(none — default)* | `agent:main` | `workspace/SOUL.md` |
| **Scout**  | `/research`  | `agent:research` | `SCOUT.md` (if exists, else built-in default) |

### How Routing Works

```python
router.resolve("/research quantum computing")
# → (Scout AgentConfig, "quantum computing")

router.resolve("hello there")
# → (Jarvis AgentConfig, "hello there")
```

1. `resolve(user_text)` — checks if text starts with any registered prefix
2. If match → returns that agent config + strips the prefix from the text
3. If no match → returns the default agent (Jarvis) + original text
4. `run()` — calls `resolve()`, builds the session key, and calls `run_agent_turn()`

### Session Isolation

Each agent gets its own session key pattern:
- Jarvis: `agent:main:repl:repl`
- Scout: `agent:research:repl:repl`

This means agents have **separate conversation histories** but share the same tools and memory store.

### `AgentConfig` Dataclass

```python
@dataclass
class AgentConfig:
    name: str                    # "Jarvis", "Scout"
    model: str                   # LLM model identifier
    soul_path: str | None        # Path to SOUL.md
    prefix: str | None           # "/research" or None (default agent)
    session_prefix: str          # "agent:main", "agent:research"
    workspace_path: str | None   # Injected into system prompt
```

The `system_prompt` property is **lazily computed** — loads the SOUL and builds the full prompt only on first access, then caches it.

---

## SOUL (System Prompt)

**File:** `src/openclaw/agent/soul.py`

The SOUL defines the agent's **personality, behavior, and boundaries**. It's a markdown file that becomes the system prompt.

### Default SOUL (`workspace/SOUL.md`)

```markdown
# Who You Are

**Name:** Jarvis
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
- Use save_memory to store important information
- Use memory_search at the start of conversations to recall context
```

### System Prompt Building

`build_system_prompt()` combines three parts:

```
┌─────────────────────────────────────┐
│  1. SOUL text (from SOUL.md)        │
│                                     │
│  2. Dynamic context:                │
│     - Current date: 2026-02-16      │
│     - Workspace: ~/.mini-openclaw   │
│                                     │
│  3. Extra context (if any)          │
└─────────────────────────────────────┘
          ↓
    Full system prompt string
    (sent as the "system" message on every LLM API call)
```

---

## Command Queue

**File:** `src/openclaw/queue/command_queue.py`

Prevents **concurrent agent turns** on the same session. Critical for multi-user channels (HTTP, Telegram).

### How It Works

```python
queue = CommandQueue()

# Session "A" — acquires lock immediately
with queue.lock("session:A"):
    run_agent_turn(...)  # Only one turn at a time for session A

# Session "B" — different session, runs in parallel
with queue.lock("session:B"):
    run_agent_turn(...)  # No conflict with session A
```

### Implementation

- `defaultdict(threading.Lock)` — one lock per session key
- A **meta-lock** protects the dictionary itself (safe get-or-create)
- The meta-lock is released *before* acquiring the session lock (so other sessions aren't blocked)
- `active_sessions` property — shows which sessions currently hold locks (monitoring)

---

## Heartbeat Scheduler

**File:** `src/openclaw/heartbeat/scheduler.py`

Runs **recurring agent tasks** without human input — like cron for your AI.

### How It Works

```
HeartbeatScheduler
     │
     ├── add(Heartbeat("morning", "every day at 07:30",
     │        prompt="What's on my agenda today?"))
     │
     ├── start() → spawns daemon thread
     │     └── Every 30 seconds: scheduler.run_pending()
     │           └── If a heartbeat is due:
     │                 ├── Build session key: "cron:morning"
     │                 ├── Call run_fn(agent_name, session_key, prompt)
     │                 └── Fire on_result callback
     │
     └── stop() → signals thread to exit
```

### Schedule Expression Parsing

Supports human-readable expressions:

| Expression                | Meaning                      |
| ------------------------- | ---------------------------- |
| `"every 5 minutes"`       | Every 5 minutes              |
| `"every 1 hour"`          | Every hour                   |
| `"every day at 07:30"`    | Daily at 7:30 AM             |
| `"every monday at 09:00"` | Weekly on Monday at 9 AM     |
| `"every 30 seconds"`      | Every 30 seconds (for testing) |

### Session Isolation

Each heartbeat gets its own session key (`cron:<name>`), so scheduled tasks **don't pollute** interactive conversations.

---

## Runtime Directory Layout

After running OpenClaw, your workspace looks like:

```
~/.mini-openclaw/                      ← WORKSPACE_DIR
├── sessions/                          ← Conversation history (JSONL files)
│   ├── agent_main_repl_repl.jsonl           ← Jarvis REPL session
│   ├── agent_research_repl_repl.jsonl       ← Scout REPL session
│   ├── agent_main_http_anonymous.jsonl      ← HTTP API session
│   ├── agent_main_telegram_12345_default.jsonl  ← Telegram chat
│   └── cron_morning.jsonl                   ← Heartbeat session
│
├── memory/                            ← Long-term memory (markdown files)
│   ├── user-preferences.md
│   ├── project-notes.md
│   └── meeting-summary-jan.md
│
├── exec-approvals.json                ← Persisted command approvals
├── SOUL.md                            ← Agent personality (Jarvis)
├── SCOUT.md                           ← Research agent personality (optional)
└── config.json                        ← Optional advanced config
```

---

## Concrete Example Walkthrough

Here's exactly what happens when you type a message in the REPL:

### Input
```
You: What files are in /tmp?
```

### Step-by-Step Execution

```
1. REPL reads "What files are in /tmp?" via input()

2. CommandQueue.lock("agent:main:repl:repl")
   → Acquires per-session lock (instant — no contention in REPL)

3. AgentRouter.resolve("What files are in /tmp?")
   → No prefix match → returns (Jarvis config, "What files are in /tmp?")
   → session_key = "agent:main:repl:repl"

4. run_agent_turn() begins:
   a. SessionStore.load("agent:main:repl:repl")
      → Reads agent_main_repl_repl.jsonl → [previous messages]

   b. _sanitize_loaded_messages() → removes any orphaned tool calls

   c. estimate_tokens() → e.g. 2,400 tokens → under threshold, no compaction

   d. Appends {"role": "user", "content": "What files are in /tmp?"}
      → SessionStore.append() → writes to JSONL

   e. LLM LOOP — Iteration 1:
      → Calls LLM API (provider-dependent):
        POST <provider_base_url>/chat/completions
        {
          "model": "<configured model e.g. claude-sonnet-4-5-20250929 or gpt-4o>",
          "messages": [
            {"role": "system", "content": "# Who You Are\n**Name:** Jarvis\n..."},
            ...previous messages...,
            {"role": "user", "content": "What files are in /tmp?"}
          ],
          "tools": [...6 tool schemas...],
          "max_tokens": 4096
        }

      ← LLM responds with tool_call:
        run_command({"command": "ls /tmp"})

      → PermissionManager.check("ls /tmp")
        → base command "ls" is in safe set → "safe"

      → subprocess.run("ls /tmp", shell=True, timeout=30)
        → stdout: "foo.txt\nbar.txt\ndata.csv"

      → on_tool_use callback prints:
        🔧 run_command: {"command": "ls /tmp"}
           → foo.txt\nbar.txt\ndata.csv

      → ATOMIC PERSIST: assistant tool-call msg + tool result msg

   f. LLM LOOP — Iteration 2:
      → Calls LLM API again (now with tool result in messages)

      ← LLM responds with text (no tool calls):
        "Here are the files in /tmp:\n- foo.txt\n- bar.txt\n- data.csv"

      → Persist assistant message → loop exits

5. CommandQueue releases the lock

6. REPL prints:
   🤖 Here are the files in /tmp:
   - foo.txt
   - bar.txt
   - data.csv
```

### What Got Persisted

**Session file** (`~/.mini-openclaw/sessions/agent_main_repl_repl.jsonl`):
```jsonl
{"role": "user", "content": "What files are in /tmp?"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_abc", "type": "function", "function": {"name": "run_command", "arguments": "{\"command\": \"ls /tmp\"}"}}]}
{"role": "tool", "tool_call_id": "call_abc", "content": "foo.txt\nbar.txt\ndata.csv"}
{"role": "assistant", "content": "Here are the files in /tmp:\n- foo.txt\n- bar.txt\n- data.csv"}
```

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
│  │ (JSONL)  │   │  Registry    │  │  Store   │         │
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

## Source File Map

| File | Lines | Purpose |
|------|-------|---------|
| `src/openclaw/main.py` | ~170 | CLI entry point, channel launching |
| `src/openclaw/config.py` | ~230 | Configuration loading (env + JSON) |
| `src/openclaw/agent/loop.py` | ~170 | Core LLM ↔ tool execution loop |
| `src/openclaw/agent/router.py` | ~150 | Multi-agent prefix-based routing |
| `src/openclaw/agent/soul.py` | ~85 | SOUL.md loading & system prompt building |
| `src/openclaw/channels/base.py` | ~30 | Abstract channel interface |
| `src/openclaw/channels/repl.py` | ~150 | Interactive terminal channel |
| `src/openclaw/channels/http_api.py` | ~130 | Flask REST API channel |
| `src/openclaw/channels/telegram.py` | ~240 | Telegram bot channel |
| `src/openclaw/session/store.py` | ~110 | JSONL session persistence |
| `src/openclaw/session/compaction.py` | ~110 | Context window compression |
| `src/openclaw/memory/store.py` | ~100 | Long-term file-based memory |
| `src/openclaw/tools/registry.py` | ~95 | Tool registration & dispatch |
| `src/openclaw/tools/shell.py` | ~55 | Shell command execution tool |
| `src/openclaw/tools/filesystem.py` | ~80 | File read/write tools |
| `src/openclaw/tools/memory_tools.py` | ~65 | Memory save/search tools |
| `src/openclaw/tools/web.py` | ~35 | Web search stub tool |
| `src/openclaw/permissions/manager.py` | ~100 | Command approval & allowlist |
| `src/openclaw/queue/command_queue.py` | ~50 | Per-session concurrency locks |
| `src/openclaw/heartbeat/scheduler.py` | ~190 | Cron-like scheduled agent tasks |
