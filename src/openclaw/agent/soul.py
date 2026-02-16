"""SOUL — Agent personality loading and system prompt building.

The SOUL is a markdown file that defines the agent's identity, behavior,
and boundaries. It gets injected as the system prompt on every API call.
"""

from __future__ import annotations

import os
from datetime import datetime

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
- You're not the user's voice — be careful about sending messages on their behalf

## Memory
You have a long-term memory system.
- Use save_memory to store important information (user preferences, key facts, project details)
- Use memory_search at the start of conversations to recall context from previous sessions
"""


def load_soul(path: str | None = None) -> str:
    """Load a SOUL from a markdown file. Falls back to the built-in default.

    Args:
        path: Path to a SOUL.md file. If None or file doesn't exist, uses default.

    Returns:
        The SOUL text as a string.
    """
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content
    return DEFAULT_SOUL


def build_system_prompt(
    soul: str,
    workspace_path: str | None = None,
    extra_context: str | None = None,
) -> str:
    """Build the full system prompt by combining the SOUL with dynamic context.

    Args:
        soul: The agent's personality text (from SOUL.md).
        workspace_path: The agent's workspace directory (injected for context).
        extra_context: Any additional context to append.

    Returns:
        The complete system prompt string.
    """
    parts = [soul]

    # Dynamic context section
    context_lines = [
        "\n## Context",
        f"- Current date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if workspace_path:
        context_lines.append(f"- Workspace: {workspace_path}")

    parts.append("\n".join(context_lines))

    if extra_context:
        parts.append(extra_context)

    return "\n\n".join(parts)
