# Mini OpenClaw — AI Agent with Memory, Tools & Scheduled Tasks

A lightweight, self-hosted AI assistant built in Python that can run on **Telegram**, a **REPL**, or **HTTP**. It remembers things across sessions, executes shell commands with approval, reads/writes files, searches the web, and runs scheduled "heartbeat" tasks — all driven by config, not code changes.

---

## What It Does

| Capability | How It Works |
|------------|-------------|
| **Multi-turn chat** | Conversations with full context, powered by Claude/GPT/Gemini via Portkey gateway |
| **Persistent memory** | `save_memory` / `memory_search` — stored as markdown files, survives restarts |
| **Session history** | JSONL-based session logs with automatic compaction when context grows too large |
| **Tool use** | The LLM can call tools: run shell commands, read/write files, search the web |
| **Permission control** | Dangerous commands require operator approval (prompted in terminal) |
| **Heartbeat scheduler** | Cron-like scheduled tasks defined in `config.json` — the agent runs autonomously on a timer |
| **Personality (SOUL)** | Customizable system prompt in `SOUL.md` — define who the agent is |
| **Multi-channel** | Telegram, HTTP API, or interactive REPL — same agent, different frontends |

---

## Architecture at a Glance

```
User (Telegram / REPL / HTTP)
  │
  ▼
Channel ──▶ AgentRouter ──▶ Agent Loop (LLM + Tool calls)
                │                  │
                │                  ├── ToolRegistry (shell, files, web, memory)
                │                  ├── PermissionManager (approve/deny)
                │                  └── SessionStore (JSONL persistence)
                │
                └── HeartbeatScheduler (config-driven, background thread)
                         │
                         └── Fires agent prompts on schedule → sends results to chat
```

---

## Quick Start

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- A **Portkey API key** ([gateway.ai.cimpress.io](https://gateway.ai.cimpress.io))
- *(Optional)* A **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)

### 1. Clone & Install

```bash
git clone <repo-url> openclaw-clone
cd openclaw-clone

# Install with all extras (telegram, http, discord, dev tools)
uv sync --all-extras
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
PORTKEY_API_KEY=your-portkey-api-key
PORTKEY_BASE_URL=https://gateway.ai.cimpress.io/v1
OPENCLAW_MODEL=@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0

# Only needed for Telegram channel:
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
```

### 3. (Optional) Configure Heartbeats

Create `~/.mini-openclaw/config.json`:

```json
{
  "heartbeats": [
    {
      "name": "time-sayer",
      "schedule": "every 1 minute",
      "prompt": "Tell me the current time and a fun fact or motivational quote. Keep it to 2-3 sentences."
    }
  ]
}
```

Schedule expressions: `every 30 seconds`, `every 5 minutes`, `every day at 07:30`, `every monday at 09:00`

### 4. Run

```bash
# Interactive REPL (default)
uv run openclaw

# Telegram bot
uv run openclaw --channel telegram

# HTTP API (port 5000)
uv run openclaw --channel http
```

---

## Available Tools (what the agent can do)

| Tool | Description |
|------|-------------|
| `shell` | Run shell commands (with permission gating) |
| `read_file` | Read file contents from the workspace |
| `write_file` | Create/overwrite files in the workspace |
| `web_search` | Search the web via DuckDuckGo |
| `save_memory` | Persist a fact to long-term memory |
| `memory_search` | Recall facts from previous sessions |

---

## Workspace Layout

Everything lives in `~/.mini-openclaw/`:

```
~/.mini-openclaw/
├── config.json          # Heartbeats, agent config (optional)
├── SOUL.md              # Agent personality prompt
├── sessions/            # JSONL conversation logs
│   ├── telegram:12345.jsonl
│   └── cron:time-sayer.jsonl
├── memory/              # Persistent memory (markdown files)
│   └── user-preferences.md
└── exec-approvals.json  # Previously approved shell commands
```

---

## Running Tests

```bash
uv run pytest
```

---

## Key Design Decisions

- **No database** — flat files (JSONL + markdown) for full inspectability
- **Portkey gateway** — model-agnostic, switch between Claude/GPT/Gemini by changing one env var
- **Config-driven heartbeats** — add scheduled tasks without touching code
- **Operator approval** — the agent can't run `rm -rf /` without you saying yes
- **Session compaction** — when context exceeds 100K tokens, older messages are summarized automatically

---

*Built as a learning exercise exploring agentic AI patterns: tool use, memory, multi-channel I/O, and autonomous scheduling.*
