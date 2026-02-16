"""Abstract base class for channel adapters.

Each channel normalizes incoming messages into (session_key, user_text)
and calls the agent router. Channels run in their own threads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ChannelAdapter(ABC):
    """Base interface for all channel adapters (REPL, HTTP, Telegram, Discord)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel identifier (e.g. 'repl', 'telegram', 'http')."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the channel (blocking or spawns its own thread)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Gracefully stop the channel."""
        ...
