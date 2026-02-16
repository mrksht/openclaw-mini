"""Tests for the JSONL session store."""

import json
import os
import tempfile

import pytest

from openclaw.session.store import SessionStore


@pytest.fixture
def store(tmp_path):
    """Create a SessionStore with a temporary directory."""
    return SessionStore(str(tmp_path / "sessions"))


class TestSessionStore:
    """Core session store functionality."""

    def test_load_empty_session(self, store):
        """Loading a nonexistent session returns an empty list."""
        assert store.load("nonexistent") == []

    def test_append_and_load(self, store):
        """Appending messages and loading them back works."""
        msg1 = {"role": "user", "content": "Hello"}
        msg2 = {"role": "assistant", "content": "Hi there!"}

        store.append("test-session", msg1)
        store.append("test-session", msg2)

        loaded = store.load("test-session")
        assert len(loaded) == 2
        assert loaded[0] == msg1
        assert loaded[1] == msg2

    def test_save_overwrites(self, store):
        """save() overwrites the entire session file."""
        store.append("s1", {"role": "user", "content": "old"})
        store.append("s1", {"role": "assistant", "content": "old reply"})

        new_messages = [{"role": "user", "content": "fresh start"}]
        store.save("s1", new_messages)

        loaded = store.load("s1")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "fresh start"

    def test_persistence_across_instances(self, tmp_path):
        """Data survives creating a new SessionStore with the same directory."""
        dir_path = str(tmp_path / "sessions")
        store1 = SessionStore(dir_path)
        store1.append("persist", {"role": "user", "content": "remember me"})

        store2 = SessionStore(dir_path)
        loaded = store2.load("persist")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "remember me"

    def test_separate_sessions(self, store):
        """Different session keys are isolated."""
        store.append("user-1", {"role": "user", "content": "I'm user 1"})
        store.append("user-2", {"role": "user", "content": "I'm user 2"})

        assert store.load("user-1")[0]["content"] == "I'm user 1"
        assert store.load("user-2")[0]["content"] == "I'm user 2"


class TestCrashSafety:
    """JSONL crash safety — corrupted lines are skipped."""

    def test_skip_corrupted_lines(self, store):
        """Corrupted lines are skipped during load."""
        store.append("crash", {"role": "user", "content": "before crash"})

        # Manually write a corrupted line
        path = store._path("crash")
        with open(path, "a") as f:
            f.write("this is not json\n")

        store.append("crash", {"role": "assistant", "content": "after crash"})

        loaded = store.load("crash")
        assert len(loaded) == 2
        assert loaded[0]["content"] == "before crash"
        assert loaded[1]["content"] == "after crash"

    def test_skip_empty_lines(self, store):
        """Empty lines are ignored."""
        path = store._path("empty-lines")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(json.dumps({"role": "user", "content": "hello"}) + "\n")
            f.write("\n")
            f.write("  \n")
            f.write(json.dumps({"role": "assistant", "content": "hi"}) + "\n")

        loaded = store.load("empty-lines")
        assert len(loaded) == 2


class TestKeySanitization:
    """Session keys are sanitized for filesystem safety."""

    def test_colons_replaced(self, store):
        """Colons in session keys become underscores."""
        assert store.sanitize_key("agent:main:user:123") == "agent_main_user_123"

    def test_slashes_replaced(self, store):
        """Slashes in keys become underscores."""
        assert store.sanitize_key("a/b/c") == "a_b_c"

    def test_safe_chars_preserved(self, store):
        """Alphanumeric, hyphens, and underscores are kept."""
        assert store.sanitize_key("my-session_01") == "my-session_01"

    def test_round_trip_with_special_key(self, store):
        """Can store and retrieve with keys containing special characters."""
        key = "agent:main:user:456"
        store.append(key, {"role": "user", "content": "works"})
        loaded = store.load(key)
        assert len(loaded) == 1
        assert loaded[0]["content"] == "works"


class TestManagement:
    """Session management operations."""

    def test_exists(self, store):
        assert not store.exists("nope")
        store.append("yes", {"role": "user", "content": "hi"})
        assert store.exists("yes")

    def test_delete(self, store):
        store.append("doomed", {"role": "user", "content": "bye"})
        assert store.exists("doomed")
        store.delete("doomed")
        assert not store.exists("doomed")
        assert store.load("doomed") == []

    def test_delete_nonexistent(self, store):
        """Deleting a nonexistent session doesn't raise."""
        store.delete("never-existed")  # should not raise

    def test_list_sessions(self, store):
        store.append("alpha", {"role": "user", "content": "a"})
        store.append("beta", {"role": "user", "content": "b"})

        sessions = store.list_sessions()
        assert "alpha" in sessions
        assert "beta" in sessions

    def test_message_count(self, store):
        assert store.message_count("empty") == 0
        store.append("count-me", {"role": "user", "content": "1"})
        store.append("count-me", {"role": "assistant", "content": "2"})
        store.append("count-me", {"role": "user", "content": "3"})
        assert store.message_count("count-me") == 3


class TestUnicode:
    """Unicode content is persisted correctly."""

    def test_unicode_content(self, store):
        msg = {"role": "user", "content": "こんにちは 🌍 café résumé"}
        store.append("unicode", msg)
        loaded = store.load("unicode")
        assert loaded[0]["content"] == "こんにちは 🌍 café résumé"

    def test_complex_content(self, store):
        """Nested structures with tool results serialize correctly."""
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "abc", "content": "result text"}
            ],
        }
        store.append("complex", msg)
        loaded = store.load("complex")
        assert loaded[0]["content"][0]["tool_use_id"] == "abc"
