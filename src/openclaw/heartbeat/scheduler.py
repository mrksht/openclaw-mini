"""Heartbeat scheduler — recurring agent tasks that fire without human input.

Each heartbeat has its own isolated session key (`cron:<name>`) so it
doesn't pollute interactive conversations. A daemon thread runs
`schedule.run_pending()` every 30 seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import schedule

logger = logging.getLogger(__name__)

# Callback type: (heartbeat_name, agent_response) -> None
OnHeartbeatResult = Callable[[str, str], None] | None


@dataclass(frozen=True)
class Heartbeat:
    """Definition of a scheduled agent task.

    Attributes:
        name: Unique identifier (used in session key and logs).
        schedule_expr: Human-readable schedule — parsed by the `schedule` library.
            Examples: "every 1 minute", "every day at 07:30", "every monday at 09:00".
        agent: Agent name to route to (default: "main").
        prompt: The user message injected when the heartbeat fires.
    """

    name: str
    schedule_expr: str
    prompt: str
    agent: str = "main"


def _parse_schedule(scheduler: schedule.Scheduler, expr: str) -> schedule.Job | None:
    """Parse a human-readable schedule expression into a schedule.Job.

    Supported formats:
        "every 5 minutes"
        "every 1 hour"
        "every day at 07:30"
        "every monday at 09:00"
        "every 30 seconds"  (for testing)
    """
    expr = expr.strip().lower()
    if not expr.startswith("every "):
        return None

    rest = expr[6:]  # strip "every "

    # "every day at HH:MM"
    if rest.startswith("day at "):
        time_str = rest[7:].strip()
        return scheduler.every().day.at(time_str)

    # "every <weekday> at HH:MM"
    weekdays = {
        "monday": scheduler.every().monday,
        "tuesday": scheduler.every().tuesday,
        "wednesday": scheduler.every().wednesday,
        "thursday": scheduler.every().thursday,
        "friday": scheduler.every().friday,
        "saturday": scheduler.every().saturday,
        "sunday": scheduler.every().sunday,
    }
    for day_name, job_fn in weekdays.items():
        if rest.startswith(f"{day_name} at "):
            time_str = rest[len(day_name) + 4:].strip()
            return job_fn.at(time_str)

    # "every N <unit>"
    parts = rest.split()
    if len(parts) >= 2:
        try:
            interval = int(parts[0])
        except ValueError:
            return None

        unit = parts[1].rstrip("s")  # normalize: "minutes" → "minute"
        unit_map = {
            "second": "seconds",
            "minute": "minutes",
            "hour": "hours",
            "day": "days",
            "week": "weeks",
        }
        sched_unit = unit_map.get(unit)
        if sched_unit:
            return getattr(scheduler.every(interval), sched_unit)

    return None


class HeartbeatScheduler:
    """Manages and runs scheduled agent tasks in a background thread.

    Usage::

        scheduler = HeartbeatScheduler(run_fn=my_agent_runner)
        scheduler.add(Heartbeat(name="morning", schedule_expr="every day at 07:30",
                                prompt="Good morning! What's on my agenda today?"))
        scheduler.start()  # spawns daemon thread
        # ...
        scheduler.stop()
    """

    def __init__(
        self,
        run_fn: Callable[[str, str, str], str],
        on_result: OnHeartbeatResult = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            run_fn: Callable(agent_name, session_key, prompt) → response.
                The actual agent execution function.
            on_result: Optional callback when a heartbeat produces output.
        """
        self._run_fn = run_fn
        self._on_result = on_result
        self._scheduler = schedule.Scheduler()
        self._heartbeats: dict[str, Heartbeat] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def add(self, heartbeat: Heartbeat) -> bool:
        """Register a heartbeat. Returns True if successfully scheduled."""
        job = _parse_schedule(self._scheduler, heartbeat.schedule_expr)
        if job is None:
            logger.warning("Invalid schedule expression: %s", heartbeat.schedule_expr)
            return False

        job.do(self._fire, heartbeat)
        self._heartbeats[heartbeat.name] = heartbeat
        logger.info("Scheduled heartbeat '%s': %s", heartbeat.name, heartbeat.schedule_expr)
        return True

    def _fire(self, heartbeat: Heartbeat) -> None:
        """Execute a heartbeat — runs the agent with an isolated session."""
        session_key = f"cron:{heartbeat.name}"
        try:
            response = self._run_fn(heartbeat.agent, session_key, heartbeat.prompt)
            logger.info("Heartbeat '%s' completed: %s", heartbeat.name, response[:100])
            if self._on_result:
                self._on_result(heartbeat.name, response)
        except Exception:
            logger.exception("Heartbeat '%s' failed", heartbeat.name)

    def start(self, check_interval: float = 30.0) -> None:
        """Start the background scheduler thread (daemon)."""
        if self._thread and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                self._scheduler.run_pending()
                self._stop_event.wait(timeout=check_interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="heartbeat")
        self._thread.start()
        logger.info("Heartbeat scheduler started (check every %.0fs)", check_interval)

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Heartbeat scheduler stopped")

    @property
    def heartbeats(self) -> list[str]:
        """List registered heartbeat names."""
        return list(self._heartbeats.keys())

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
