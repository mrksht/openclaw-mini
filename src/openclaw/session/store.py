"""JSONL-based session persistence.

Each session is stored as a JSONL file (one JSON object per line).
Append-only writes ensure crash safety — at most one line is lost on crash.
"""

from __future__ import annotations

import json
import os
import re


class SessionStore:
    """Manages conversation sessions as JSONL files on disk.

    Each session is identified by a string key (e.g. "agent:main:user:12345").
    Keys are sanitized for filesystem safety.
    """

    def __init__(self, sessions_dir: str) -> None:
        self._dir = sessions_dir
        os.makedirs(self._dir, exist_ok=True)

    @property
    def sessions_dir(self) -> str:
        return self._dir

    # ── Key → Path ──

    @staticmethod
    def sanitize_key(key: str) -> str:
        """Convert a session key to a filesystem-safe filename (without extension)."""
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", key)

    def _path(self, session_key: str) -> str:
        safe = self.sanitize_key(session_key)
        return os.path.join(self._dir, f"{safe}.jsonl")

    # ── Read ──

    def load(self, session_key: str) -> list[dict]:
        """Load all messages from a session. Returns [] if session doesn't exist.

        Skips lines that fail JSON parsing (crash-safety).
        """
        path = self._path(session_key)
        if not os.path.exists(path):
            return []

        messages: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    messages.append(json.loads(stripped))
                except json.JSONDecodeError:
                    # Skip corrupted lines — crash safety
                    continue
        return messages

    # ── Write ──

    def append(self, session_key: str, message: dict) -> None:
        """Append a single message to a session file (crash-safe)."""
        path = self._path(session_key)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def save(self, session_key: str, messages: list[dict]) -> None:
        """Overwrite the session file with the full message list.

        Used after compaction or session reset.
        """
        path = self._path(session_key)
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    # ── Management ──

    def exists(self, session_key: str) -> bool:
        """Check if a session file exists."""
        return os.path.exists(self._path(session_key))

    def delete(self, session_key: str) -> None:
        """Delete a session file."""
        path = self._path(session_key)
        if os.path.exists(path):
            os.remove(path)

    def list_sessions(self) -> list[str]:
        """List all session filenames (without .jsonl extension)."""
        if not os.path.exists(self._dir):
            return []
        return [
            f[:-6]  # strip .jsonl
            for f in os.listdir(self._dir)
            if f.endswith(".jsonl")
        ]

    def message_count(self, session_key: str) -> int:
        """Count messages in a session without loading them all into memory."""
        path = self._path(session_key)
        if not os.path.exists(path):
            return 0
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
