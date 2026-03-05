"""Heartbeat scheduler — cron-like scheduled tasks for the agent.

Runs heartbeats on a background daemon thread using the ``schedule`` library.
Each heartbeat fires the agent with a pre-defined prompt and delivers the
result via a callback (e.g. Telegram DM, Slack DM, terminal print).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable

import schedule

logger = logging.getLogger(__name__)

# Type aliases
RunFn = Callable[[str, str, str], str]        # (agent_name, session_key, prompt) -> response
OnResultFn = Callable[[str, str], None] | None  # (heartbeat_name, response) -> None


@dataclass(frozen=True)
class Heartbeat:
    """A single scheduled task.

    Attributes:
        name: Unique identifier, e.g. ``"morning-briefing"``.
        schedule_expr: Human-readable schedule, e.g. ``"every day at 07:30"``.
        prompt: The prompt sent to the agent when the heartbeat fires.
        agent: Which agent handles it (default: ``"main"``).
    """

    name: str
    schedule_expr: str
    prompt: str
    agent: str = "main"


# ── Schedule expression parser ────────────────────────────────────────────────

_WEEKDAYS = {
    "monday": "monday",
    "tuesday": "tuesday",
    "wednesday": "wednesday",
    "thursday": "thursday",
    "friday": "friday",
    "saturday": "saturday",
    "sunday": "sunday",
}


def _parse_schedule(sched: schedule.Scheduler, expr: str) -> schedule.Job | None:
    """Translate a human-readable schedule expression into a ``schedule`` Job.

    Supported formats::

        "every 5 minutes"
        "every 1 hour"
        "every day at 07:30"
        "every monday at 09:00"
        "every 30 seconds"

    Returns ``None`` if the expression cannot be parsed.
    """
    expr = expr.strip().lower()

    # Strip leading "every " — all our expressions start with it
    if not expr.startswith("every "):
        return None
    rest = expr[len("every "):]

    # "every day at HH:MM"
    m = re.match(r"day at (\d{2}:\d{2})$", rest)
    if m:
        return sched.every().day.at(m.group(1))

    # "every <weekday> at HH:MM"
    for day_name, attr in _WEEKDAYS.items():
        m = re.match(rf"{day_name} at (\d{{2}}:\d{{2}})$", rest)
        if m:
            job = getattr(sched.every(), attr)
            return job.at(m.group(1))

    # "every N <unit>" — e.g. "every 5 minutes", "every 1 hour", "every 30 seconds"
    m = re.match(r"(\d+)\s+(seconds?|minutes?|hours?)$", rest)
    if m:
        interval = int(m.group(1))
        unit = m.group(2)
        # Normalize to plural form for the schedule library attribute
        if not unit.endswith("s"):
            unit += "s"
        return getattr(sched.every(interval), unit)

    return None


# ── Heartbeat Scheduler ──────────────────────────────────────────────────────


class HeartbeatScheduler:
    """Manages scheduled heartbeats on a background thread.

    Usage::

        scheduler = HeartbeatScheduler(run_fn=my_runner, on_result=my_handler)
        scheduler.add(Heartbeat(name="quote", schedule_expr="every 1 minute", prompt="..."))
        scheduler.start(check_interval=30)
        # ... later ...
        scheduler.stop()
    """

    def __init__(
        self,
        run_fn: RunFn,
        on_result: OnResultFn = None,
    ) -> None:
        self._run_fn = run_fn
        self._on_result = on_result
        self._scheduler = schedule.Scheduler()
        self._heartbeats: dict[str, Heartbeat] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Registration ──────────────────────────────────────────────────────

    def add(self, heartbeat: Heartbeat) -> bool:
        """Register a heartbeat.  Returns ``False`` if the expression is invalid."""
        job = _parse_schedule(self._scheduler, heartbeat.schedule_expr)
        if job is None:
            logger.warning("Invalid schedule expression: %s", heartbeat.schedule_expr)
            return False

        job.do(self._fire, heartbeat)
        self._heartbeats[heartbeat.name] = heartbeat
        return True

    # ── Execution ─────────────────────────────────────────────────────────

    def _fire(self, heartbeat: Heartbeat) -> None:
        """Called by the schedule library when a heartbeat is due."""
        session_key = f"cron:{heartbeat.name}"
        try:
            response = self._run_fn(heartbeat.agent, session_key, heartbeat.prompt)
            if self._on_result:
                self._on_result(heartbeat.name, response)
        except Exception:
            logger.exception("Heartbeat '%s' failed", heartbeat.name)

    # ── Background thread ─────────────────────────────────────────────────

    def start(self, check_interval: int = 30) -> None:
        """Start the background scheduler thread.

        Args:
            check_interval: Seconds between pending-job checks (default 30).
        """
        if self._thread is not None and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.is_set():
                self._scheduler.run_pending()
                self._stop_event.wait(timeout=check_interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="heartbeat")
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def heartbeats(self) -> list[str]:
        """Return registered heartbeat names."""
        return list(self._heartbeats.keys())

    @property
    def is_running(self) -> bool:
        """Whether the background thread is active."""
        return self._thread is not None and self._thread.is_alive()
