"""Shell command execution tool.

Runs shell commands with timeout and permission checks.
"""

from __future__ import annotations

import subprocess
from typing import Any

from openclaw.permissions.manager import PermissionManager
from openclaw.tools.registry import Tool


def create_shell_tool(permission_manager: PermissionManager) -> Tool:
    """Create the run_command tool with permission checking.

    Args:
        permission_manager: Handles command safety checks and approvals.
    """

    def run_command(tool_input: dict[str, Any]) -> str:
        command = tool_input["command"]

        # Check permissions
        safety = permission_manager.check(command)
        if safety == "needs_approval":
            approved = permission_manager.request_approval(command)
            if not approved:
                return "Permission denied. Command requires approval."

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr
            return output.strip() if output.strip() else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {e}"

    return Tool(
        name="run_command",
        description="Run a shell command on the user's computer",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"}
            },
            "required": ["command"],
        },
        handler=run_command,
    )
