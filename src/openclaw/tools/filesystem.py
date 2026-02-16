"""Filesystem tools — read_file and write_file.

Basic file I/O for the agent.
"""

from __future__ import annotations

import os
from typing import Any

from openclaw.tools.registry import Tool

MAX_READ_SIZE = 50_000  # characters


def create_read_file_tool() -> Tool:
    """Create the read_file tool."""

    def read_file(tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(MAX_READ_SIZE)
            if len(content) == MAX_READ_SIZE:
                content += "\n... (file truncated)"
            return content
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except IsADirectoryError:
            return f"Error: Path is a directory: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

    return Tool(
        name="read_file",
        description="Read a file from the filesystem",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"}
            },
            "required": ["path"],
        },
        handler=read_file,
    )


def create_write_file_tool() -> Tool:
    """Create the write_file tool."""

    def write_file(tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        content = tool_input["content"]
        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    return Tool(
        name="write_file",
        description="Write content to a file (creates parent directories if needed)",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
