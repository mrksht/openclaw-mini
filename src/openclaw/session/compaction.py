"""Context window compaction — summarize old messages when token limit approaches.

Uses a rough token estimate (chars / 4) and asks the LLM to compress
the older half of the conversation into a summary.
"""

from __future__ import annotations

import json
from typing import Any


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: serialize to JSON and divide char count by 4.

    Not exact, but good enough for deciding when to compact.
    """
    return len(json.dumps(messages, ensure_ascii=False)) // 4


def _split_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split messages at the midpoint into old and recent halves.

    Tries to split on a user-message boundary so we don't break
    an assistant→tool flow in the middle.
    """
    mid = len(messages) // 2

    # Walk forward from midpoint to find a user message boundary
    for i in range(mid, len(messages)):
        if messages[i].get("role") == "user":
            return messages[:i], messages[i:]

    # Walk backward if no user message found after midpoint
    for i in range(mid, 0, -1):
        if messages[i].get("role") == "user":
            return messages[:i], messages[i:]

    # Fallback: split at midpoint
    return messages[:mid], messages[mid:]


_COMPACTION_PROMPT = """Summarize the following conversation concisely. \
Preserve all important facts, decisions, user preferences, file paths, \
variable names, and action outcomes. Be specific — do not generalize. \
Format as a bullet list.

Conversation to summarize:
{conversation}"""


def compact(
    messages: list[dict],
    client: Any,
    model: str,
    threshold: int = 100_000,
) -> list[dict]:
    """Compact messages if estimated tokens exceed the threshold.

    Splits at midpoint, asks the LLM to summarize the old half,
    and prepends the summary to the recent half.

    Args:
        messages: The full conversation (excluding system prompt).
        client: Portkey/OpenAI-compatible client.
        model: Model identifier for the summarization call.
        threshold: Token threshold; no-op if under this.

    Returns:
        The (possibly compacted) message list.
    """
    if estimate_tokens(messages) < threshold:
        return messages

    old_half, recent_half = _split_messages(messages)

    if not old_half:
        return messages  # Nothing to compact

    # Build the conversation text for summarization
    conversation_text = _format_for_summary(old_half)

    # Ask the LLM to summarize
    summary_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise conversation summarizer."},
            {"role": "user", "content": _COMPACTION_PROMPT.format(conversation=conversation_text)},
        ],
        max_tokens=2048,
    )

    summary = summary_response.choices[0].message.content or "(empty summary)"

    # Prepend summary as a context message
    summary_msg = {
        "role": "user",
        "content": f"[Conversation summary of {len(old_half)} earlier messages]\n\n{summary}",
    }

    return [summary_msg] + recent_half


def _format_for_summary(messages: list[dict]) -> str:
    """Format messages into readable text for the summarizer."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "tool":
            tool_id = msg.get("tool_call_id", "")
            lines.append(f"[Tool result {tool_id}]: {content[:500]}")
        elif msg.get("tool_calls"):
            tool_names = [tc["function"]["name"] for tc in msg["tool_calls"]]
            lines.append(f"Assistant: [called tools: {', '.join(tool_names)}]")
            if content:
                lines.append(f"Assistant: {content}")
        else:
            lines.append(f"{role.capitalize()}: {content}")

    return "\n".join(lines)
