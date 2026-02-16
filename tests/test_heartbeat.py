"""Tests for the heartbeat scheduler."""

import threading
import time
from unittest.mock import MagicMock

from openclaw.heartbeat.scheduler import Heartbeat, HeartbeatScheduler, _parse_schedule

import schedule as schedule_lib


class TestParseSchedule:
    def test_every_n_minutes(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "every 5 minutes")
        assert job is not None

    def test_every_n_seconds(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "every 30 seconds")
        assert job is not None

    def test_every_day_at(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "every day at 07:30")
        assert job is not None

    def test_every_monday_at(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "every monday at 09:00")
        assert job is not None

    def test_invalid_expression(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "run at noon")
        assert job is None

    def test_every_1_hour(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "every 1 hour")
        assert job is not None

    def test_case_insensitive(self):
        s = schedule_lib.Scheduler()
        job = _parse_schedule(s, "Every Day At 08:00")
        assert job is not None


class TestHeartbeatScheduler:
    def test_add_heartbeat(self):
        scheduler = HeartbeatScheduler(run_fn=MagicMock())
        hb = Heartbeat(name="test", schedule_expr="every 1 minutes", prompt="Hello")
        assert scheduler.add(hb) is True
        assert "test" in scheduler.heartbeats

    def test_add_invalid_schedule(self):
        scheduler = HeartbeatScheduler(run_fn=MagicMock())
        hb = Heartbeat(name="bad", schedule_expr="nonsense", prompt="Hello")
        assert scheduler.add(hb) is False
        assert "bad" not in scheduler.heartbeats

    def test_fire_calls_run_fn(self):
        run_fn = MagicMock(return_value="Done")
        scheduler = HeartbeatScheduler(run_fn=run_fn)
        hb = Heartbeat(name="fire-test", schedule_expr="every 1 minutes",
                       prompt="Do something", agent="main")

        # Call _fire directly
        scheduler._fire(hb)

        run_fn.assert_called_once_with("main", "cron:fire-test", "Do something")

    def test_fire_calls_on_result_callback(self):
        run_fn = MagicMock(return_value="Agent response")
        on_result = MagicMock()
        scheduler = HeartbeatScheduler(run_fn=run_fn, on_result=on_result)
        hb = Heartbeat(name="cb-test", schedule_expr="every 1 minutes", prompt="Go")

        scheduler._fire(hb)

        on_result.assert_called_once_with("cb-test", "Agent response")

    def test_fire_handles_exception(self):
        run_fn = MagicMock(side_effect=RuntimeError("boom"))
        scheduler = HeartbeatScheduler(run_fn=run_fn)
        hb = Heartbeat(name="err-test", schedule_expr="every 1 minutes", prompt="Fail")

        # Should not raise
        scheduler._fire(hb)

    def test_start_and_stop(self):
        scheduler = HeartbeatScheduler(run_fn=MagicMock())
        scheduler.start(check_interval=0.1)
        assert scheduler.is_running
        scheduler.stop()
        assert not scheduler.is_running

    def test_start_idempotent(self):
        scheduler = HeartbeatScheduler(run_fn=MagicMock())
        scheduler.start(check_interval=0.1)
        scheduler.start(check_interval=0.1)  # Should not spawn a second thread
        assert scheduler.is_running
        scheduler.stop()

    def test_heartbeat_names(self):
        scheduler = HeartbeatScheduler(run_fn=MagicMock())
        scheduler.add(Heartbeat(name="a", schedule_expr="every 1 minutes", prompt="A"))
        scheduler.add(Heartbeat(name="b", schedule_expr="every 5 minutes", prompt="B"))
        assert sorted(scheduler.heartbeats) == ["a", "b"]
