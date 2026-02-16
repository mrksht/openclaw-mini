"""Configuration — centralizes Portkey client setup and app settings.

Supports two modes:
1. Module-level constants (backward compatible, env-var driven)
2. JSON config file at ~/.mini-openclaw/config.json (for advanced setups)

Uses the same Portkey gateway pattern as Vista's project-rag.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

# Load .env from project root if present
load_dotenv()

# ── Portkey / LLM Settings ──

PORTKEY_API_KEY = os.getenv("PORTKEY_API_KEY", "")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://gateway.ai.cimpress.io/v1")
DEFAULT_MODEL = os.getenv(
    "OPENCLAW_MODEL", "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

# Available models via Portkey gateway:
#
# Anthropic:
#   @Anthropic/eu.anthropic.claude-opus-4-6-v1
#   @Anthropic/eu.anthropic.claude-opus-4-5-20251101-v1:0
#   @Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0
#   @Anthropic/eu.anthropic.claude-sonnet-4-20250514-v1:0
#   @Anthropic/eu.anthropic.claude-haiku-4-5-20251001-v1:0
#
# OpenAI:
#   @OpenAI/o4-mini, @OpenAI/o3
#   @OpenAI/gpt-5.2, @OpenAI/gpt-5.1, @OpenAI/gpt-5, @OpenAI/gpt-5-pro, @OpenAI/gpt-5-mini
#   @OpenAI/gpt-5.1-codex, @OpenAI/gpt-5.1-codex-mini, @OpenAI/gpt-5.1-codex-max
#   @OpenAI/gpt-5-codex, @OpenAI/gpt-4o, @OpenAI/gpt-4o-mini
#
# Google:
#   @Google/gemini-3-pro-preview, @Google/gemini-3-flash-preview
#   @Google/gemini-2.5-pro, @Google/gemini-2.5-flash, @Google/gemini-2.5-flash-lite
#
# Embeddings:
#   @OpenAI/text-embedding-3-small
#   @Google/gemini-embedding-001

# ── Workspace Settings ──

WORKSPACE_DIR = os.path.expanduser(os.getenv("OPENCLAW_WORKSPACE", "~/.mini-openclaw"))
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, "sessions")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
APPROVALS_FILE = os.path.join(WORKSPACE_DIR, "exec-approvals.json")
SOUL_PATH = os.path.join(WORKSPACE_DIR, "SOUL.md")

# ── Agent Settings ──

MAX_TOOL_TURNS = 20
COMPACTION_THRESHOLD_TOKENS = 100_000


def get_portkey_client():
    """Create a Portkey client instance.

    Uses the same pattern as Vista's project-rag:
    - api_key from PORTKEY_API_KEY env var
    - base_url from PORTKEY_BASE_URL env var (defaults to Vista gateway)
    """
    from portkey_ai import Portkey

    return Portkey(
        api_key=PORTKEY_API_KEY,
        base_url=PORTKEY_BASE_URL,
    )


def ensure_workspace():
    """Create workspace directories if they don't exist."""
    for d in [WORKSPACE_DIR, SESSIONS_DIR, MEMORY_DIR]:
        os.makedirs(d, exist_ok=True)


# ── JSON Config File Support ──


@dataclass
class AgentDef:
    """Agent definition from config file."""

    name: str
    model: str = ""
    soul_path: str | None = None
    prefix: str | None = None
    session_prefix: str = "agent:main"


@dataclass
class ChannelDef:
    """Channel definition from config file."""

    enabled: bool = False
    port: int = 5000
    host: str = "0.0.0.0"


@dataclass
class HeartbeatDef:
    """Heartbeat definition from config file."""

    name: str
    schedule: str
    prompt: str
    agent: str = "main"


_DEFAULT_SAFE_COMMANDS = [
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "echo", "date", "pwd", "whoami", "which", "file",
    "git", "python", "python3", "node", "npm", "npx",
    "uv", "pip", "ruff", "pytest", "go", "cargo", "make",
]


@dataclass
class AppConfig:
    """Full application configuration loaded from config.json.

    Provides sensible defaults for all settings. Can be constructed
    from a JSON file, from a dict, or with no arguments (all defaults).
    """

    workspace: str = field(default_factory=lambda: WORKSPACE_DIR)
    default_model: str = field(default_factory=lambda: DEFAULT_MODEL)
    agents: dict[str, AgentDef] = field(default_factory=dict)
    channels: dict[str, ChannelDef] = field(default_factory=dict)
    heartbeats: list[HeartbeatDef] = field(default_factory=list)
    safe_commands: list[str] = field(default_factory=lambda: list(_DEFAULT_SAFE_COMMANDS))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Build config from a parsed JSON dict."""
        agents = {}
        for key, agent_data in data.get("agents", {}).items():
            agents[key] = AgentDef(
                name=agent_data.get("name", key.capitalize()),
                model=agent_data.get("model", ""),
                soul_path=agent_data.get("soul_path"),
                prefix=agent_data.get("prefix"),
                session_prefix=agent_data.get("session_prefix", f"agent:{key}"),
            )

        channels = {}
        for key, ch_data in data.get("channels", {}).items():
            channels[key] = ChannelDef(
                enabled=ch_data.get("enabled", False),
                port=ch_data.get("port", 5000),
                host=ch_data.get("host", "0.0.0.0"),
            )

        heartbeats = []
        for hb_data in data.get("heartbeats", []):
            heartbeats.append(HeartbeatDef(
                name=hb_data["name"],
                schedule=hb_data["schedule"],
                prompt=hb_data["prompt"],
                agent=hb_data.get("agent", "main"),
            ))

        return cls(
            workspace=os.path.expanduser(data.get("workspace", WORKSPACE_DIR)),
            default_model=data.get("default_model", DEFAULT_MODEL),
            agents=agents,
            channels=channels,
            heartbeats=heartbeats,
            safe_commands=data.get("permissions", {}).get("safe_commands", _DEFAULT_SAFE_COMMANDS),
        )

    @classmethod
    def from_file(cls, path: str) -> AppConfig:
        """Load config from a JSON file. Returns defaults if file doesn't exist."""
        if not os.path.exists(path):
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def load(cls, workspace: str | None = None) -> AppConfig:
        """Load config from the standard location.

        Checks:
        1. OPENCLAW_CONFIG env var
        2. <workspace>/config.json
        3. Falls back to defaults
        """
        config_path = os.getenv("OPENCLAW_CONFIG")
        if config_path and os.path.exists(config_path):
            return cls.from_file(config_path)

        ws = workspace or WORKSPACE_DIR
        default_path = os.path.join(ws, "config.json")
        return cls.from_file(default_path)

    def validate(self) -> list[str]:
        """Validate the config and return a list of warnings (empty = valid)."""
        warnings: list[str] = []

        if not self.default_model:
            warnings.append("No default_model specified")

        for name, agent in self.agents.items():
            if agent.soul_path and not os.path.exists(agent.soul_path):
                warnings.append(f"Agent '{name}': soul_path '{agent.soul_path}' not found")

        for hb in self.heartbeats:
            if not hb.name:
                warnings.append("Heartbeat missing 'name'")
            if not hb.schedule:
                warnings.append(f"Heartbeat '{hb.name}' missing 'schedule'")
            if not hb.prompt:
                warnings.append(f"Heartbeat '{hb.name}' missing 'prompt'")

        return warnings
