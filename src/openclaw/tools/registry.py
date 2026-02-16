"""Tool registry — register tools and generate schemas for the LLM.

Tools are simple: a name, a description, an input schema, and a handler function.
The registry collects them and provides schemas for the OpenAI-compatible API (via Portkey).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    """A single tool that the agent can use.

    Attributes:
        name: Unique tool identifier (e.g. "run_command").
        description: Human-readable description for the LLM.
        input_schema: JSON Schema for the tool's parameters.
        handler: Function that executes the tool. Takes a dict, returns a string.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    """Collects tools and dispatches execution.

    Usage:
        registry = ToolRegistry()
        registry.register(Tool(name="echo", description="...", input_schema={...}, handler=fn))
        schemas = registry.get_schemas()  # for Anthropic API
        result = registry.execute("echo", {"text": "hello"})
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ValueError if name already taken."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name, or None."""
        return self._tools.get(name)

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas in OpenAI function-calling format (used by Portkey)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name. Returns the result string.

        If the tool doesn't exist, returns an error string (never raises).
        If the tool handler raises, catches and returns the error.
        """
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        try:
            result = tool.handler(tool_input)
            return str(result)
        except Exception as e:
            return f"Error executing {name}: {e}"

    @property
    def tool_names(self) -> list[str]:
        """List registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)
