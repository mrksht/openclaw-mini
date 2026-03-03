"""Tiered context assembly for the agent loop.

Builds the final ``api_messages`` list that is sent to the LLM on every turn
using a three-tier model:

  Cold  — long-term memories (all keys from MemoryStore, injected as a single
           block right after the system prompt).
  Warm  — older session messages that precede the hot window.  These may
           already be a compaction summary (a single summary message) or raw
           older turns if compaction hasn't triggered yet.  They are included
           verbatim; trimming/summarisation is left to the compaction step in
           the agent loop.
  Hot   — the most recent ``hot_turns`` user-turn pairs (user + assistant +
           any tool calls in between), kept verbatim.  The current user
           message is always part of the hot tier.

Prompt injection order (recommended by Anthropic / OpenAI research):

  1. System instructions  ← passed separately; not in the returned list
  2. Cold: long-term memory block
  3. Warm: older session messages / compaction summary
  4. Hot: recent verbatim turns
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openclaw.memory.store import MemoryStore


# ── Hot / Warm split ──────────────────────────────────────────────────────────


def _split_hot_warm(
    messages: list[dict],
    hot_turns: int,
) -> tuple[list[dict], list[dict]]:
    """Split *messages* into (warm, hot) by counting user-message turns from
    the end.

    A "turn" is one user message (and all the assistant / tool messages that
    follow it before the next user message).

    If there are fewer than *hot_turns* user messages the entire list is
    returned as hot and warm is empty.

    The boundary is placed at the index of the ``hot_turns``-th user message
    from the end, so the warm slice never starts mid-tool-call.
    """
    user_turns_seen = 0

    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_turns_seen += 1
            if user_turns_seen == hot_turns:
                # i is the start of the hot window
                return messages[:i], messages[i:]

    # Fewer user messages than hot_turns — everything is hot
    return [], messages


# ── Cold tier: long-term memory block ─────────────────────────────────────────


def _build_cold_block(memory_store: "MemoryStore") -> str | None:
    """Return a formatted string of all stored memories, or None if empty."""
    keys = memory_store.list_keys()
    if not keys:
        return None

    parts: list[str] = ["[Long-term memory]"]
    for key in keys:
        content = memory_store.load(key)
        if content:
            parts.append(f"--- {key} ---\n{content.strip()}")

    return "\n\n".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────


def build_tiered_context(
    system_prompt: str,
    messages: list[dict],
    memory_store: "MemoryStore | None" = None,
    hot_turns: int = 20,
) -> list[dict]:
    """Assemble the ordered ``api_messages`` list for an LLM call.

    Args:
        system_prompt: The agent's full system prompt (SOUL + context).
        messages: Full session history including the current user message.
        memory_store: Long-term memory store.  Pass ``None`` to skip cold
            injection (backward-compatible with old call sites).
        hot_turns: Number of most-recent user turns to keep verbatim in the
            hot tier.  Default: 20.

    Returns:
        A list of message dicts ready to pass as ``messages=`` to the LLM,
        with the system prompt as the first entry.
    """
    api_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # ── Cold tier ─────────────────────────────────────────────────────────
    if memory_store is not None:
        cold_block = _build_cold_block(memory_store)
        if cold_block:
            api_messages.append({"role": "user", "content": cold_block})
            # Acknowledge so the message list stays well-formed
            # (some providers reject a user message with no following turn)
            api_messages.append({
                "role": "assistant",
                "content": "Memory context loaded.",
            })

    # ── Warm + Hot tiers ──────────────────────────────────────────────────
    warm, hot = _split_hot_warm(messages, hot_turns)
    api_messages.extend(warm)
    api_messages.extend(hot)

    return api_messages
