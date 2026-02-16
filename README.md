# Mini OpenClaw

A lightweight, self-hosted AI assistant built in Python. It connects to **Telegram**, runs as a **REPL**, or exposes an **HTTP API** — with persistent memory, tool execution, permission gating, and config-driven scheduled tasks (heartbeats).

Built on top of the [Portkey AI Gateway](https://gateway.ai.cimpress.io) for model-agnostic LLM access (Claude, GPT, Gemini).

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Config File](#config-file-optional)
  - [SOUL.md — Agent Personality](#soulmd--agent-personality)
- [Running](#running)
  - [Interactive REPL](#interactive-repl)
  - [Telegram Bot](#telegram-bot)
  - [HTTP API](#http-api)
- [Tools](#tools)
- [Heartbeats (Scheduled Tasks)](#heartbeats-scheduled-tasks)
- [Multi-Agent Routing](#multi-agent-routing)
- [Workspace Layout](#workspace-layout)
- [Available Models](#available-models)
- [Development](#development)
  - [Running Tests](#running-tests)
  - [Linting](#linting)
  - [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Multi-turn conversations** with full context, powered by any LLM via Portkey
- **Persistent memory** — save and recall facts across sessions (`save_memory` / `memory_search`)
- **Session history** — JSONL-based logs with automatic compaction when context exceeds 100K tokens
- **Tool use** — the LLM can run shell commands, read/write files, search the web
- **Permission control** — dangerous shell commands require operator approval in the terminal
- **Heartbeat scheduler** — cron-like tasks defined in `config.json`, fired autonomously on a timer
- **Customizable personality** — define who the agent is via `SOUL.md`
- **Multi-channel** — Telegram, HTTP API, or interactive REPL
- **Multi-agent routing** — prefix-based routing (e.g., `/research` routes to a different agent)

---

## Prerequisites

| Requirement | Version | Install |
|-------------|---------|---------|
| **Python** | 3.12+ | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` |
| **Portkey API Key** | — | Get from [Portkey Dashboard](https://gateway.ai.cimpress.io) |
| **Telegram Bot Token** | — | *(Optional)* Create via [@BotFather](https://t.me/BotFather) on Telegram |

---

## Installation

### 1. Clone the repository

```bash
git clone <repo-url> openclaw-clone
cd openclaw-clone
```

### 2. Install dependencies

```bash
# Core only (REPL mode)
uv sync

# With Telegram support
uv sync --extra telegram

# With HTTP API support
uv sync --extra http

# Everything (Telegram + HTTP + Discord + dev tools)
uv sync --all-extras
```

> **Important:** Use `--all-extras` if you want multiple channels. Running `uv sync --extra telegram` alone will *uninstall* other extras. To combine specific ones:
> ```bash
> uv sync --extra telegram --extra http --extra dev
> ```

### 3. Verify installation

```bash
uv run openclaw --help
```

Expected output:
```
usage: openclaw [-h] [--config CONFIG] [--channel {repl,http,telegram}]

Mini OpenClaw — AI assistant

options:
  -h, --help            show this help message and exit
  --config CONFIG, -c CONFIG
                        Path to config.json file
  --channel {repl,http,telegram}
                        Channel to start (default: repl)
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# ── Required ──
PORTKEY_API_KEY=your-portkey-api-key-here

# ── Optional (have sensible defaults) ──
PORTKEY_BASE_URL=https://gateway.ai.cimpress.io/v1
OPENCLAW_MODEL=@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0
OPENCLAW_WORKSPACE=~/.mini-openclaw

# ── Telegram only ──
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORTKEY_API_KEY` | Yes | — | Your Portkey gateway API key |
| `PORTKEY_BASE_URL` | No | `https://gateway.ai.cimpress.io/v1` | Portkey gateway URL |
| `OPENCLAW_MODEL` | No | `@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | Default LLM model |
| `OPENCLAW_WORKSPACE` | No | `~/.mini-openclaw` | Workspace directory for sessions, memory, config |
| `OPENCLAW_CONFIG` | No | — | Explicit path to config.json (overrides auto-discovery) |
| `TELEGRAM_BOT_TOKEN` | Telegram only | — | Bot token from @BotFather |

### Config File (Optional)

The app auto-discovers `~/.mini-openclaw/config.json` on startup. You can also pass `--config <path>` explicitly.

```json
{
  "default_model": "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "workspace": "~/.mini-openclaw",

  "heartbeats": [
    {
      "name": "time-sayer",
      "schedule": "every 1 minute",
      "prompt": "Tell me the current time and a fun fact or motivational quote. Keep it to 2-3 sentences.",
      "agent": "main"
    }
  ],

  "permissions": {
    "safe_commands": [
      "ls", "cat", "head", "tail", "wc", "grep", "find",
      "echo", "date", "pwd", "whoami", "which", "file",
      "git", "python", "python3", "node", "npm", "npx",
      "uv", "pip", "ruff", "pytest", "go", "cargo", "make"
    ]
  }
}
```

### SOUL.md — Agent Personality

Place a `SOUL.md` file at `~/.mini-openclaw/SOUL.md` to define the agent's personality. A default is provided at `workspace/SOUL.md` in the repo.

Example:
```markdown
# Who You Are

**Name:** Jarvis
**Role:** Personal AI assistant

## Personality
- Be genuinely helpful, not performatively helpful
- Skip the "Great question!" — just help
- Be concise when needed, thorough when it matters
```

---

## Running

### Interactive REPL

```bash
uv run openclaw
```

Type messages, get responses. Press `Ctrl+C` to exit.

### Telegram Bot

**Setup (one-time):**

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow prompts
2. Copy the bot token into your `.env` as `TELEGRAM_BOT_TOKEN`
3. Install the Telegram extra: `uv sync --extra telegram`

**Run:**

```bash
uv run openclaw --channel telegram
```

Output:
```
Mini OpenClaw — Telegram
  Model: @Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0
  Agents: Jarvis, Scout
  Tools: shell, read_file, write_file, save_memory, memory_search, web_search
  Heartbeats: time-sayer (starts on first message)
```

Open your bot in Telegram and send `/start`. The bot auto-captures your chat ID on first interaction. Heartbeats begin firing after your first message.

**Permission approval:** When the bot tries to run a shell command (e.g., the user asks "create a file"), the terminal where openclaw is running will prompt:

```
  ⚠️  Telegram user requesting command: echo "hello" > test.txt
  Allow? (y/n):
```

Safe commands (ls, cat, git, python, etc.) are auto-approved.

### HTTP API

```bash
uv sync --extra http
uv run openclaw --channel http
```

Starts a Flask server on `0.0.0.0:5000`. Send POST requests:

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!", "user_id": "user-1"}'
```

---

## Tools

The agent has access to these tools (LLM decides when to use them):

| Tool | Description | Permission |
|------|-------------|------------|
| `shell` | Execute shell commands in the workspace | Safe commands auto-approved; others require operator approval |
| `read_file` | Read the contents of a file | Always allowed |
| `write_file` | Create or overwrite a file | Always allowed |
| `save_memory` | Persist a fact to long-term memory (markdown file) | Always allowed |
| `memory_search` | Search long-term memory for previously saved facts | Always allowed |
| `web_search` | Search the web via DuckDuckGo | Always allowed |

**Safe commands** (auto-approved): `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `find`, `echo`, `date`, `pwd`, `whoami`, `which`, `file`, `git`, `python`, `python3`, `node`, `npm`, `npx`, `uv`, `pip`, `ruff`, `pytest`, `go`, `cargo`, `make`

Customize the safe list in `config.json` under `permissions.safe_commands`.

---

## Heartbeats (Scheduled Tasks)

Heartbeats are autonomous tasks the agent runs on a schedule without user input. Define them in `~/.mini-openclaw/config.json`:

```json
{
  "heartbeats": [
    {
      "name": "morning-briefing",
      "schedule": "every day at 07:30",
      "prompt": "Good morning! Give me a motivational quote to start the day.",
      "agent": "main"
    },
    {
      "name": "health-check",
      "schedule": "every 5 minutes",
      "prompt": "Run 'date' and report the current server time.",
      "agent": "main"
    }
  ]
}
```

**Supported schedule formats:**

| Format | Example |
|--------|---------|
| Every N seconds | `every 30 seconds` |
| Every N minutes | `every 5 minutes` |
| Every N hours | `every 2 hours` |
| Daily at time | `every day at 07:30` |
| Weekly on day | `every monday at 09:00` |

Each heartbeat gets its own isolated session (`cron:<name>`) so it doesn't pollute interactive conversations. Results are sent to the owner's Telegram chat (auto-detected from the first user interaction).

---

## Multi-Agent Routing

The system supports multiple agents with prefix-based routing:

| Agent | Prefix | Description |
|-------|--------|-------------|
| **Jarvis** | *(default — no prefix)* | Main assistant, uses `SOUL.md` |
| **Scout** | `/research` | Research-focused agent, uses `SCOUT.md` if present |

Send `/research What are the latest trends in AI?` in Telegram to route to Scout.

Add more agents by creating a `SCOUT.md` in `~/.mini-openclaw/` or by defining agents in `config.json`.

---

## Workspace Layout

All runtime data lives in `~/.mini-openclaw/` (configurable via `OPENCLAW_WORKSPACE`):

```
~/.mini-openclaw/
├── config.json              # App config: heartbeats, permissions, agents
├── SOUL.md                  # Agent personality prompt
├── SCOUT.md                 # (Optional) Scout agent personality
├── exec-approvals.json      # Previously approved shell commands (cached)
├── sessions/                # Conversation history (JSONL)
│   ├── telegram:123456.jsonl
│   ├── cron:time-sayer.jsonl
│   └── repl:default.jsonl
└── memory/                  # Persistent memory (markdown files)
    └── user-preferences.md
```

- **Sessions** are JSONL files — one JSON object per message. They auto-compact (summarize) when exceeding 100K tokens.
- **Memory** files are plain markdown — fully human-readable and editable.
- **Approvals** cache previously approved commands so you don't re-approve the same command.

---

## Available Models

Set via `OPENCLAW_MODEL` env var or `default_model` in config.json:

**Anthropic:**
- `@Anthropic/eu.anthropic.claude-opus-4-6-v1`
- `@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0` *(default)*
- `@Anthropic/eu.anthropic.claude-haiku-4-5-20251001-v1:0`

**OpenAI:**
- `@OpenAI/gpt-5.2`, `@OpenAI/gpt-5.1`, `@OpenAI/gpt-5`
- `@OpenAI/o4-mini`, `@OpenAI/o3`
- `@OpenAI/gpt-4o`, `@OpenAI/gpt-4o-mini`

**Google:**
- `@Google/gemini-3-pro-preview`, `@Google/gemini-3-flash-preview`
- `@Google/gemini-2.5-pro`, `@Google/gemini-2.5-flash`

---

## Development

### Running Tests

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_config.py
```

### Linting

```bash
# Check for issues
uv run ruff check .

# Auto-fix
uv run ruff check . --fix

# Format
uv run ruff format .
```

### Project Structure

```
src/openclaw/
├── main.py                  # CLI entry point, channel launchers
├── config.py                # Env vars, AppConfig, Portkey client setup
├── agent/
│   ├── loop.py              # Core agent loop: LLM call → tool execution → repeat
│   ├── router.py            # Multi-agent routing (prefix-based)
│   └── soul.py              # SOUL.md loader
├── channels/
│   ├── base.py              # Abstract channel interface
│   ├── repl.py              # Interactive terminal REPL
│   ├── telegram.py          # Telegram bot (python-telegram-bot)
│   ├── http_api.py          # Flask REST API
│   └── discord_ch.py        # Discord bot (placeholder)
├── heartbeat/
│   └── scheduler.py         # Background cron scheduler (schedule lib)
├── memory/
│   └── store.py             # Markdown-based persistent memory
├── permissions/
│   └── manager.py           # Command approval/deny with safe-list
├── queue/
│   └── command_queue.py     # Thread-safe command queue
├── session/
│   ├── store.py             # JSONL session persistence
│   └── compaction.py        # Context window compaction (summarization)
└── tools/
    ├── registry.py          # Tool registration and lookup
    ├── shell.py             # Shell command execution tool
    ├── filesystem.py        # File read/write tools
    ├── memory_tools.py      # save_memory / memory_search tools
    └── web.py               # Web search tool (DuckDuckGo)

tests/                       # pytest test suite (12 test files)
workspace/
└── SOUL.md                  # Default agent personality (copied to ~/.mini-openclaw/)
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'telegram'` | Run `uv sync --extra telegram` |
| `ModuleNotFoundError: No module named 'flask'` | Run `uv sync --extra http` |
| `TELEGRAM_BOT_TOKEN not set in .env` | Add your bot token to the `.env` file |
| `PORTKEY_API_KEY` is empty | Add your Portkey API key to the `.env` file |
| Permission denied on shell commands | The operator terminal shows an approval prompt — type `y` to allow |
| Heartbeats not firing | They start after first Telegram message. Check `config.json` has heartbeats defined |
| `uv sync --extra X` uninstalled other extras | Use `uv sync --all-extras` or combine: `uv sync --extra telegram --extra dev` |
| Config not loading | Ensure `~/.mini-openclaw/config.json` exists, or pass `--config <path>` |

---

## License

Internal project — Vista.
