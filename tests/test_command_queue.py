"""Tests for the per-session command queue."""

import threading
import time

from openclaw.queue.command_queue import CommandQueue


class TestCommandQueue:
    def test_basic_lock_and_release(self):
        queue = CommandQueue()
        with queue.lock("session-1"):
            assert "session-1" in queue.active_sessions
        assert "session-1" not in queue.active_sessions

    def test_different_sessions_concurrent(self):
        """Two different sessions can process in parallel."""
        queue = CommandQueue()
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def worker(session_key: str):
            with queue.lock(session_key):
                barrier.wait()  # Both threads must reach this point
                results.append(session_key)

        t1 = threading.Thread(target=worker, args=("s1",))
        t2 = threading.Thread(target=worker, args=("s2",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both should have completed (were running concurrently)
        assert sorted(results) == ["s1", "s2"]

    def test_same_session_sequential(self):
        """Two messages to the same session execute sequentially."""
        queue = CommandQueue()
        order: list[int] = []
        lock_acquired = threading.Event()

        def first():
            with queue.lock("shared"):
                lock_acquired.set()
                time.sleep(0.1)
                order.append(1)

        def second():
            lock_acquired.wait(timeout=5)
            time.sleep(0.01)  # Ensure first() holds the lock
            with queue.lock("shared"):
                order.append(2)

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # First must complete before second starts
        assert order == [1, 2]

    def test_active_sessions_empty_initially(self):
        queue = CommandQueue()
        assert queue.active_sessions == []

    def test_exception_releases_lock(self):
        """Lock is released even if the work raises an exception."""
        queue = CommandQueue()

        try:
            with queue.lock("error-session"):
                raise ValueError("boom")
        except ValueError:
            pass

        # Lock should be released — another acquire should succeed immediately
        acquired = threading.Event()

        def acquire():
            with queue.lock("error-session"):
                acquired.set()

        t = threading.Thread(target=acquire)
        t.start()
        t.join(timeout=2)
        assert acquired.is_set()

    def test_reentrant_different_keys(self):
        """Locking different keys from the same thread works."""
        queue = CommandQueue()
        with queue.lock("a"):
            with queue.lock("b"):
                assert "a" in queue.active_sessions
                assert "b" in queue.active_sessions
