"""List directory tool — explore project structure.

Returns a formatted tree view of files and subdirectories.  Useful for the agent
to understand project layout before reading or editing files.
"""

from __future__ import annotations

import os
from typing import Any

from openclaw.tools.registry import Tool

_MAX_ENTRIES = 200  # prevent overwhelming output on huge directories
_MAX_DEPTH = 5      # default max recursion depth


def _human_size(nbytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            if unit == "B":
                return f"{nbytes}{unit}"
            return f"{nbytes:.1f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.1f}TB"


def _list_tree(
    root: str,
    max_depth: int = _MAX_DEPTH,
    show_hidden: bool = False,
    _depth: int = 0,
    _count: list[int] | None = None,
) -> list[str]:
    """Build a tree listing of a directory.

    Returns a list of formatted lines like::

        ├── main.py  (1.2KB)
        ├── utils/
        │   ├── helpers.py  (800B)
        │   └── constants.py  (340B)
        └── config.py  (520B)
    """
    if _count is None:
        _count = [0]

    lines: list[str] = []

    try:
        entries = sorted(os.listdir(root))
    except PermissionError:
        return [f"  {'│   ' * _depth}(permission denied)"]
    except FileNotFoundError:
        return [f"Error: Directory not found: {root}"]

    if not show_hidden:
        entries = [e for e in entries if not e.startswith(".")]

    # Separate dirs and files, dirs first
    dirs = [e for e in entries if os.path.isdir(os.path.join(root, e))]
    files = [e for e in entries if not os.path.isdir(os.path.join(root, e))]
    all_entries = dirs + files

    for i, entry in enumerate(all_entries):
        if _count[0] >= _MAX_ENTRIES:
            remaining = len(all_entries) - i
            lines.append(f"  {'│   ' * _depth}... ({remaining} more entries truncated)")
            break

        _count[0] += 1
        is_last = i == len(all_entries) - 1
        connector = "└── " if is_last else "├── "
        prefix = "│   " * _depth

        full_path = os.path.join(root, entry)
        is_dir = os.path.isdir(full_path)

        if is_dir:
            lines.append(f"  {prefix}{connector}{entry}/")
            if _depth < max_depth - 1:
                children = _list_tree(
                    full_path,
                    max_depth=max_depth,
                    show_hidden=show_hidden,
                    _depth=_depth + 1,
                    _count=_count,
                )
                lines.extend(children)
        else:
            try:
                size = os.path.getsize(full_path)
                size_str = _human_size(size)
                lines.append(f"  {prefix}{connector}{entry}  ({size_str})")
            except OSError:
                lines.append(f"  {prefix}{connector}{entry}")

    return lines


def create_list_dir_tool() -> Tool:
    """Create the list_directory tool."""

    def list_directory(tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path", ".")
        max_depth = tool_input.get("max_depth", _MAX_DEPTH)
        show_hidden = tool_input.get("show_hidden", False)

        path = os.path.expanduser(path)

        if not os.path.exists(path):
            return f"Error: Path does not exist: {path}"

        if not os.path.isdir(path):
            return f"Error: Path is not a directory: {path}"

        abs_path = os.path.abspath(path)
        lines = [f"📂 {abs_path}/\n"]

        tree = _list_tree(
            abs_path,
            max_depth=min(max_depth, 10),  # hard cap at 10
            show_hidden=show_hidden,
        )
        lines.extend(tree)

        # Summary counts
        total_dirs = sum(1 for ln in tree if ln.rstrip().endswith("/"))
        total_files = len(tree) - total_dirs
        lines.append(f"\n({total_dirs} directories, {total_files} files shown)")

        return "\n".join(lines)

    return Tool(
        name="list_directory",
        description=(
            "List files and subdirectories in a directory as a tree view. "
            "Useful for exploring project structure before reading files."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: current directory)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How many levels deep to recurse (default: 5, max: 10)",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files/dirs starting with '.' (default: false)",
                },
            },
            "required": ["path"],
        },
        handler=list_directory,
    )
