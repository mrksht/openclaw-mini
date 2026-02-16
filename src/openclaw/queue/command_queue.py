"""Per-session command queue — prevents concurrent agent turns on the same session.

Uses a simple defaultdict(Lock) pattern. Different sessions can process
simultaneously; the same session queues messages in FIFO order.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Generator


class CommandQueue:
    """Per-session locking for concurrency safety.

    Example::

        queue = CommandQueue()
        with queue.lock("session:123"):
            run_agent_turn(...)  # Only one turn at a time per session
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._meta_lock = threading.Lock()  # Protects _locks dict itself

    @contextmanager
    def lock(self, session_key: str) -> Generator[None, None, None]:
        """Acquire a per-session lock. Blocks if another turn is in progress.

        Uses a meta-lock to safely get-or-create the session lock,
        then releases the meta-lock before acquiring the session lock
        to avoid blocking other sessions.
        """
        with self._meta_lock:
            session_lock = self._locks[session_key]

        session_lock.acquire()
        try:
            yield
        finally:
            session_lock.release()

    @property
    def active_sessions(self) -> list[str]:
        """Return session keys that currently hold locks (for monitoring)."""
        with self._meta_lock:
            return [key for key, lock in self._locks.items() if lock.locked()]
