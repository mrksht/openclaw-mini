"""Permission manager for shell command execution.

Provides a safety layer: known-safe commands auto-execute, everything else
requires approval. Approvals are persisted so you're never asked twice.
"""

from __future__ import annotations

import json
import os
from typing import Callable

DEFAULT_SAFE_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "date", "whoami", "echo",
    "pwd", "which", "git", "python", "python3", "node", "npm", "npx",
    "uv", "pip", "find", "grep", "sort", "uniq", "tr", "cut", "env",
})


class PermissionManager:
    """Manages command execution permissions.

    Three outcomes for any command:
    - "safe": Base command is in the safe set → auto-execute
    - "approved": Exact command was previously approved → auto-execute
    - "needs_approval": Unknown command → ask user

    Approvals persist to a JSON file on disk.
    """

    def __init__(
        self,
        approvals_file: str,
        safe_commands: frozenset[str] | None = None,
        approval_callback: Callable[[str], bool] | None = None,
    ) -> None:
        """
        Args:
            approvals_file: Path to the JSON file for persistent approvals.
            safe_commands: Set of base commands that are always allowed.
            approval_callback: Function called to request user approval.
                Takes the command string, returns True if approved.
                If None, unapproved commands are always denied.
        """
        self._approvals_file = approvals_file
        self._safe_commands = safe_commands or DEFAULT_SAFE_COMMANDS
        self._approval_callback = approval_callback

    def check(self, command: str) -> str:
        """Check if a command is safe to execute.

        Returns:
            "safe" — base command is in the safe set
            "approved" — exact command was previously approved
            "needs_approval" — command requires user approval
        """
        base_cmd = command.strip().split()[0] if command.strip() else ""
        if base_cmd in self._safe_commands:
            return "safe"

        approvals = self._load_approvals()
        if command in approvals.get("allowed", []):
            return "approved"

        return "needs_approval"

    def request_approval(self, command: str) -> bool:
        """Request user approval for a command.

        Uses the approval_callback if set. Persists the decision.
        Returns True if approved, False if denied.
        """
        if self._approval_callback:
            approved = self._approval_callback(command)
        else:
            approved = False

        self._save_approval(command, approved)
        return approved

    def _load_approvals(self) -> dict:
        if os.path.exists(self._approvals_file):
            try:
                with open(self._approvals_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {"allowed": [], "denied": []}
        return {"allowed": [], "denied": []}

    def _save_approval(self, command: str, approved: bool) -> None:
        approvals = self._load_approvals()
        key = "allowed" if approved else "denied"
        if command not in approvals.get(key, []):
            approvals.setdefault(key, []).append(command)
        os.makedirs(os.path.dirname(self._approvals_file) or ".", exist_ok=True)
        with open(self._approvals_file, "w") as f:
            json.dump(approvals, f, indent=2)

    @property
    def safe_commands(self) -> frozenset[str]:
        return self._safe_commands
