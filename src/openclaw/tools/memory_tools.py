"""Memory tools — save_memory and memory_search.

These tools bridge the agent to the MemoryStore for long-term knowledge.
"""

from __future__ import annotations

from typing import Any

from openclaw.memory.store import MemoryStore
from openclaw.tools.registry import Tool


def create_save_memory_tool(memory_store: MemoryStore) -> Tool:
    """Create the save_memory tool."""

    def save_memory(tool_input: dict[str, Any]) -> str:
        key = tool_input["key"]
        content = tool_input["content"]
        memory_store.save(key, content)
        return f"Saved to memory: {key}"

    return Tool(
        name="save_memory",
        description=(
            "Save important information to long-term memory. "
            "Use for user preferences, key facts, and anything worth remembering across sessions."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Short label, e.g. 'user-preferences', 'project-notes'",
                },
                "content": {
                    "type": "string",
                    "description": "The information to remember",
                },
            },
            "required": ["key", "content"],
        },
        handler=save_memory,
    )


def create_memory_search_tool(memory_store: MemoryStore) -> Tool:
    """Create the memory_search tool."""

    def memory_search(tool_input: dict[str, Any]) -> str:
        query = tool_input["query"]
        return memory_store.search(query)

    return Tool(
        name="memory_search",
        description="Search long-term memory for relevant information",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for",
                }
            },
            "required": ["query"],
        },
        handler=memory_search,
    )
