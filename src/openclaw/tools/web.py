"""Web search tool — powered by Tavily.

Requires TAVILY_API_KEY to be set in the environment. If the key is absent
the tool returns a helpful message instead of raising.
"""

from __future__ import annotations

from typing import Any

from openclaw.tools.registry import Tool

_MAX_RESULTS = 5


def _import_tavily_client():
    """Import and return TavilyClient. Isolated so tests can monkeypatch it."""
    from tavily import TavilyClient  # type: ignore[import-untyped]
    return TavilyClient


def _format_results(results: list[dict[str, Any]]) -> str:
    """Format Tavily result dicts into a readable numbered list."""
    if not results:
        return "No results found."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        lines.append(f"{i}. **{title}**")
        if url:
            lines.append(f"   URL: {url}")
        if snippet:
            if len(snippet) > 400:
                snippet = snippet[:400].rsplit(" ", 1)[0] + "…"
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def create_web_search_tool(api_key: str | None = None) -> Tool:
    """Create a web_search tool backed by the Tavily API.

    Args:
        api_key: Tavily API key. Pass ``None`` or omit to get a graceful
                 "not configured" response when the tool is called.
    """

    def web_search(tool_input: dict[str, Any]) -> str:
        query = tool_input["query"]
        if not api_key:
            return (
                "Web search is not configured. "
                "Set the TAVILY_API_KEY environment variable to enable it."
            )
        try:
            client = _import_tavily_client()(api_key=api_key)
            response = client.search(query, max_results=_MAX_RESULTS)
            results: list[dict[str, Any]] = response.get("results", [])
            return _format_results(results)
        except Exception as exc:  # noqa: BLE001
            return f"Web search failed: {exc}"

    return Tool(
        name="web_search",
        description=(
            "Search the web for current information, news, facts, or anything "
            "outside your training data. Returns titles, URLs, and snippets."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — be specific for better results",
                }
            },
            "required": ["query"],
        },
        handler=web_search,
    )
