"""Web search tool (stub).

In production, you'd connect to a real search API (SerpAPI, Brave Search, etc.).
This stub returns a placeholder to keep the tool available.
"""

from __future__ import annotations

from typing import Any

from openclaw.tools.registry import Tool


def create_web_search_tool() -> Tool:
    """Create the web_search stub tool."""

    def web_search(tool_input: dict[str, Any]) -> str:
        query = tool_input["query"]
        return (
            f"[Web search stub] Results for: {query}\n"
            "Note: Connect a real search API (SerpAPI, Brave Search, etc.) "
            "for actual web search results."
        )

    return Tool(
        name="web_search",
        description="Search the web for information",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
        handler=web_search,
    )
