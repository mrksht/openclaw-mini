"""Core agent loop — the LLM ↔ tool execution cycle.

Calls the LLM via Portkey (OpenAI-compatible), executes any requested tools,
feeds results back, and repeats until the model is done or max iterations hit.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from openclaw.session.compaction import compact, estimate_tokens
from openclaw.session.store import SessionStore
from openclaw.tools.registry import ToolRegistry

# Type for the on_tool_use callback: (tool_name, tool_input, tool_result) -> None
OnToolUseCallback = Callable[[str, dict, str], None] | None


def _serialize_tool_calls(tool_calls) -> list[dict[str, Any]]:
    """Convert OpenAI tool_call objects to JSON-serializable dicts."""
    serialized = []
    for tc in tool_calls:
        serialized.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        })
    return serialized


def _serialize_assistant_message(message) -> dict[str, Any]:
    """Convert an OpenAI ChatCompletionMessage to a serializable dict."""
    msg: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        msg["tool_calls"] = _serialize_tool_calls(message.tool_calls)
    return msg


def _sanitize_loaded_messages(messages: list[dict]) -> list[dict]:
    """Remove trailing orphaned assistant tool-call messages.

    If the session was interrupted between saving an assistant message with
    tool_calls and saving the corresponding tool results (e.g. crash, old bug),
    those orphan messages would cause Anthropic/Bedrock to reject the request.

    We walk backwards and strip any trailing assistant messages that have
    tool_calls without subsequent tool-result messages.
    """
    if not messages:
        return messages

    # Walk backwards from the end — find any orphaned tool_calls
    while messages:
        last = messages[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            # This assistant message has tool_calls but nothing after it
            # (or only more orphaned assistant messages) — remove it
            messages.pop()
        else:
            break

    return messages


def run_agent_turn(
    client,
    model: str,
    system_prompt: str,
    session_key: str,
    user_text: str,
    session_store: SessionStore,
    tool_registry: ToolRegistry,
    max_turns: int = 20,
    on_tool_use: OnToolUseCallback = None,
    compaction_threshold: int = 100_000,
) -> str:
    """Run one full agent turn: load session, call LLM in a loop, save.

    Args:
        client: Portkey client instance.
        model: Model identifier (e.g. "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0").
        system_prompt: The system prompt (SOUL + context).
        session_key: Session identifier for persistence.
        user_text: The user's message text.
        session_store: For loading/saving conversation history.
        tool_registry: For executing tools.
        max_turns: Max LLM calls per turn (prevents infinite tool loops).
        on_tool_use: Optional callback for each tool execution.
        compaction_threshold: Token threshold for automatic compaction.

    Returns:
        The assistant's final text response.
    """
    # Load existing conversation and sanitize orphaned tool-call messages
    messages = _sanitize_loaded_messages(session_store.load(session_key))

    # Compact if approaching context window limit
    if estimate_tokens(messages) >= compaction_threshold:
        messages = compact(messages, client, model, threshold=compaction_threshold)
        session_store.save(session_key, messages)  # Overwrite with compacted version

    # Add user message
    user_msg = {"role": "user", "content": user_text}
    messages.append(user_msg)
    session_store.append(session_key, user_msg)

    # Build the messages list with system prompt
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    # Get tool schemas
    tools = tool_registry.get_schemas()

    for _ in range(max_turns):
        # Call the LLM
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 4096,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        assistant_message = choice.message

        # Serialize the assistant message
        serialized_msg = _serialize_assistant_message(assistant_message)

        # If no tool calls, persist and return immediately
        # Note: OpenAI returns "tool_calls", Anthropic via Portkey returns "tool_use"
        has_tool_calls = choice.finish_reason in ("tool_calls", "tool_use") and assistant_message.tool_calls
        if not has_tool_calls:
            messages.append(serialized_msg)
            session_store.append(session_key, serialized_msg)
            return assistant_message.content or ""

        # We have tool calls — execute tools first, then persist everything
        # together so we never have an assistant with tool_calls but no results.
        tool_result_msgs: list[dict[str, Any]] = []

        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_input = {}

            # Execute the tool
            result = tool_registry.execute(tool_name, tool_input)

            # Notify callback
            if on_tool_use:
                on_tool_use(tool_name, tool_input, result)

            # Build tool result message (OpenAI format)
            tool_result_msgs.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            })

        # Persist the assistant message + all tool results atomically
        messages.append(serialized_msg)
        session_store.append(session_key, serialized_msg)
        api_messages.append(serialized_msg)

        for tool_msg in tool_result_msgs:
            messages.append(tool_msg)
            session_store.append(session_key, tool_msg)
            api_messages.append(tool_msg)

    return "(max tool turns reached)"
