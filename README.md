# Mini OpenClaw

A lightweight, self-hosted AI assistant built in Python. It connects to **Telegram**, **Slack**, runs as a **REPL**, or exposes an **HTTP API** — with persistent memory, tool execution, permission gating, and config-driven scheduled tasks (heartbeats).

Works with **Anthropic (Claude)**, **OpenAI (GPT)**, or the **Portkey AI Gateway** — pick your provider, set one env var, and go.

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
  - [Slack Bot](#slack-bot)
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

- **Multi-turn conversations** with full context, powered by Anthropic, OpenAI, or Portkey
- **Tiered context memory** — three-tier prompt injection: recent turns verbatim (hot) → older turns summarized (warm) → long-term facts always injected (cold)
- **Persistent memory** — long-term facts auto-injected into every prompt; also searchable via `save_memory` / `memory_search`
- **Session history** — JSONL-based logs with automatic compaction when context exceeds 100K tokens
- **Tool use** — the LLM can run shell commands, read/write files, search the web
- **Permission control** — dangerous shell commands require operator approval in the terminal
- **Heartbeat scheduler** — cron-like tasks defined in `config.json`, fired autonomously on a timer
- **Customizable personality** — define who the agent is via `SOUL.md`
- **Multi-channel** — Telegram, Slack, HTTP API, or interactive REPL
- **Slack MR digest** — monitors Slack channels for GitLab MR links, sends a private DM digest to the owner
- **Multi-agent routing** — prefix-based routing (e.g., `/research` routes to a different agent)

---

## Prerequisites

| Requirement | Version | Install |
|-------------|---------|---------|
| **Python** | 3.12+ | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` |
| **LLM API Key** | — | **One of:** Anthropic, OpenAI, or Portkey (see [LLM Provider Setup](#llm-provider-setup)) |
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

# With Slack support
uv sync --extra slack

# With HTTP API support
uv sync --extra http

# Everything (Telegram + Slack + HTTP + Discord + dev tools)
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
  --channel {repl,http,telegram,slack}
                        Channel to start (default: repl)
```

---

## Configuration

### LLM Provider Setup

Mini OpenClaw supports three LLM providers. You only need **one**. Set the corresponding API key in your `.env` file and the app auto-detects which provider to use.

#### Option A: Anthropic (Claude) — Recommended for most users

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENCLAW_MODEL=claude-sonnet-4-5-20250929
```

You'll also need the `openai` package (used as the HTTP client for Anthropic's OpenAI-compatible endpoint):

```bash
uv add openai
```

#### Option B: OpenAI (GPT)

```env
OPENAI_API_KEY=sk-your-key-here
OPENCLAW_MODEL=gpt-4o
```

Install the OpenAI SDK:

```bash
uv add openai
```

#### Option C: Portkey Gateway (multi-provider)

```env
PORTKEY_API_KEY=your-portkey-key-here
PORTKEY_BASE_URL=https://api.portkey.ai/v1
OPENCLAW_MODEL=@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Portkey is pre-installed as a core dependency — no extra packages needed.

#### Explicit provider override

If you have multiple API keys set, use `LLM_PROVIDER` to force one:

```env
LLM_PROVIDER=anthropic   # or "openai" or "portkey"
```

### Environment Variables

Create a `.env` file in the project root:

```env
# ── LLM Provider (pick one) ──
ANTHROPIC_API_KEY=sk-ant-...    # Option A: Anthropic directly
OPENAI_API_KEY=sk-...           # Option B: OpenAI directly
PORTKEY_API_KEY=...             # Option C: Portkey gateway

# ── Optional ──
LLM_PROVIDER=                   # Force provider: "anthropic", "openai", or "portkey"
OPENCLAW_MODEL=claude-sonnet-4-5-20250929  # Model name (provider-specific)
OPENCLAW_WORKSPACE=~/.mini-openclaw

# ── Telegram only ──
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here

# ── Slack only (uv sync --extra slack) ──
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token
SLACK_OWNER_ID=your-slack-member-id
SLACK_CHANNEL_ID=                   # Optional — leave empty to scan all bot channels

# ── GitLab (for MR review tool) ──
GITLAB_URL=https://gitlab.com
GITLAB_PRIVATE_TOKEN=glpat-your-token
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | One of three | — | Anthropic API key (direct Claude access) |
| `OPENAI_API_KEY` | One of three | — | OpenAI API key (direct GPT access) |
| `PORTKEY_API_KEY` | One of three | — | Portkey gateway API key |
| `LLM_PROVIDER` | No | *(auto-detected)* | Force provider: `anthropic`, `openai`, or `portkey` |
| `OPENCLAW_MODEL` | No | `@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | Model identifier (use provider-native names) |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Custom OpenAI-compatible endpoint |
| `PORTKEY_BASE_URL` | No | `https://api.portkey.ai/v1` | Portkey gateway URL |
| `OPENCLAW_WORKSPACE` | No | `~/.mini-openclaw` | Workspace directory |
| `OPENCLAW_HOT_TURNS` | No | `20` | Number of most-recent user turns kept verbatim in the hot tier of the prompt |
| `OPENCLAW_CONFIG` | No | — | Explicit path to config.json |
| `TELEGRAM_BOT_TOKEN` | Telegram only | — | Bot token from @BotFather |
| `SLACK_BOT_TOKEN` | Slack only | — | Slack bot token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Slack only | — | Slack app-level token (`xapp-...`) for Socket Mode |
| `SLACK_OWNER_ID` | Slack only | — | Your Slack member ID (DM digest recipient) |
| `SLACK_CHANNEL_ID` | No | *(all bot channels)* | Limit scanning to one channel |
| `GITLAB_URL` | No | `https://gitlab.com` | GitLab instance URL (for `gitlab_mr` tool) |
| `GITLAB_PRIVATE_TOKEN` | No | — | GitLab personal access token (enables MR enrichment) |

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

### Slack Bot

**Setup (one-time):**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Give it a name (e.g., "OpenClaw") and select your workspace

3. **Enable Socket Mode:**
   - Sidebar → **Socket Mode** → toggle **Enable Socket Mode** on
   - You'll be prompted to create an **App-Level Token** — name it (e.g., `openclaw-socket`), add the scope `connections:write`, and click **Generate**
   - Copy the token (`xapp-...`) — this is your `SLACK_APP_TOKEN`

4. **Subscribe to bot events:**
   - Sidebar → **Event Subscriptions** → toggle **Enable Events** on
   - Under **Subscribe to bot events**, add these events:
     - `message.channels` — messages in public channels
     - `message.groups` — messages in private channels
     - `message.im` — direct messages to the bot

5. **Add bot token scopes:**
   - Sidebar → **OAuth & Permissions** → scroll to **Scopes → Bot Token Scopes**
   - Add these scopes:

   | Scope | Why it's needed |
   |-------|----------------|
   | `channels:history` | Read messages in public channels the bot is in |
   | `channels:read` | List and get info about public channels |
   | `groups:history` | Read messages in private channels the bot is in |
   | `groups:read` | List and get info about private channels |
   | `chat:write` | Send messages (DM digests to the owner) |
   | `im:history` | Read DM messages sent to the bot |
   | `im:read` | Check if a conversation is a DM (`conversations_info`) |
   | `im:write` | Open DM conversations with the owner |
   | `users:read` | Resolve user IDs to display names |

6. **Install the app:**
   - Sidebar → **Install App** → **Install to Workspace** → **Allow**
   - Copy the **Bot User OAuth Token** (`xoxb-...`) — this is your `SLACK_BOT_TOKEN`

7. **Invite the bot to channels:**
   - In Slack, go to each channel you want monitored → type `/invite @OpenClaw`

8. **Find your Slack Member ID:**
   - Click your profile picture in Slack → **Profile** → **⋮ (More)** → **Copy member ID**
   - This is your `SLACK_OWNER_ID`

9. **Set env vars** in `.env`:
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-level-token
   SLACK_OWNER_ID=U0XXXXXXX
   SLACK_CHANNEL_ID=              # Optional — leave empty to scan all bot channels
   ```

10. *(Optional)* For GitLab MR enrichment, also set `GITLAB_URL` and `GITLAB_PRIVATE_TOKEN`

**Install & Run:**

```bash
uv sync --extra slack
uv run openclaw --channel slack
```

**What it does:**
- Monitors all Slack channels the bot is a member of for GitLab MR links
- Sends you a private **DM digest** with MR details (title, state, author, reviewers, approval status)
- Supports DM conversations with the bot owner (you) through the agent router
- Heartbeat results (e.g., daily MR digest) are delivered as DMs to the owner
- Never posts into public channels — listen-only

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
| `memory_search` | Search long-term memory for a specific fact (all memories are also auto-injected into every prompt) | Always allowed |
| `web_search` | Search the web via DuckDuckGo | Always allowed |
| `gitlab_mr` | Fetch GitLab MR details (title, state, author, reviewers, approval) | Always allowed (requires `GITLAB_PRIVATE_TOKEN`) |

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

Each heartbeat gets its own isolated session (`cron:<name>`) so it doesn't pollute interactive conversations. Results are sent to the owner's Telegram chat or Slack DM (auto-detected from the channel in use).

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
- **Memory** files are plain markdown — fully human-readable and editable. All memory files are automatically injected into every LLM prompt (cold tier), so the agent always has access to saved facts without needing to call `memory_search` first.
- **Approvals** cache previously approved commands so you don't re-approve the same command.

---

## Available Models

Set via `OPENCLAW_MODEL` env var or `default_model` in config.json. Use **provider-native model names** matching your chosen provider:

### Anthropic (direct)
| Model | `OPENCLAW_MODEL` value |
|-------|------------------------|
| Claude Opus 4 | `claude-opus-4-0-20250514` |
| Claude Sonnet 4.5 | `claude-sonnet-4-5-20250929` |
| Claude Sonnet 4 | `claude-sonnet-4-20250514` |
| Claude Haiku 3.5 | `claude-3-5-haiku-20241022` |

### OpenAI (direct)
| Model | `OPENCLAW_MODEL` value |
|-------|------------------------|
| GPT-4o | `gpt-4o` |
| GPT-4o mini | `gpt-4o-mini` |
| o3 | `o3` |
| o4-mini | `o4-mini` |

### Portkey Gateway
Use the `@Provider/model` format:

| Provider | Examples |
|----------|----------|
| Anthropic | `@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0` *(default)* |
| OpenAI | `@OpenAI/gpt-4o`, `@OpenAI/o4-mini` |
| Google | `@Google/gemini-2.5-pro`, `@Google/gemini-2.5-flash` |

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
│   ├── slack_ch.py          # Slack bot (slack-bolt, Socket Mode)
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
│   ├── compaction.py        # Context window compaction (summarization)
│   └── context_builder.py   # Tiered context assembly: cold → warm → hot
└── tools/
    ├── registry.py          # Tool registration and lookup
    ├── shell.py             # Shell command execution tool
    ├── filesystem.py        # File read/write tools
    ├── memory_tools.py      # save_memory / memory_search tools
    ├── web.py               # Web search tool (DuckDuckGo)
    └── gitlab_mr.py         # GitLab MR details tool

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
| `ModuleNotFoundError: No module named 'slack_bolt'` | Run `uv sync --extra slack` |
| `SLACK_BOT_TOKEN not set in .env` | Add your Slack bot token (`xoxb-...`) to `.env` |
| `SLACK_APP_TOKEN not set in .env` | Add your Slack app-level token (`xapp-...`) to `.env` — needed for Socket Mode |
| `SLACK_OWNER_ID not set in .env` | Set your Slack member ID in `.env` (find it in Slack profile → ⋮ → Copy member ID) |
| `TELEGRAM_BOT_TOKEN not set in .env` | Add your bot token to the `.env` file |
| No LLM API key set | Set one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `PORTKEY_API_KEY` in `.env` |
| `ImportError: openai package required` | Run `uv add openai` (needed for Anthropic/OpenAI direct providers) |
| Permission denied on shell commands | The operator terminal shows an approval prompt — type `y` to allow |
| Heartbeats not firing | They start after first Telegram message (Telegram) or immediately (Slack). Check `config.json` has heartbeats defined |
| `uv sync --extra X` uninstalled other extras | Use `uv sync --all-extras` or combine: `uv sync --extra telegram --extra dev` |
| Config not loading | Ensure `~/.mini-openclaw/config.json` exists, or pass `--config <path>` |

---

## License

Personal project — Rakshit.
