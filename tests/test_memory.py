"""Tests for the memory store."""

import pytest

from openclaw.memory.store import MemoryStore


class TestMemoryStore:
    def test_save_and_load(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("prefs", "Favorite color: blue")
        assert ms.load("prefs") == "Favorite color: blue"

    def test_load_missing(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        assert ms.load("nonexistent") is None

    def test_overwrite(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("key", "old value")
        ms.save("key", "new value")
        assert ms.load("key") == "new value"

    def test_search_matches(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("food", "Favorite restaurant: Elvies")
        ms.save("color", "Favorite color: blue")

        result = ms.search("restaurant")
        assert "Elvies" in result
        assert "blue" not in result

    def test_search_multiple_matches(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("a", "python is great")
        ms.save("b", "python async patterns")

        result = ms.search("python")
        assert "great" in result
        assert "async" in result

    def test_search_no_match(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("x", "nothing relevant")
        result = ms.search("quantum")
        assert "No matching" in result

    def test_search_empty_query(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        result = ms.search("")
        assert "No matching" in result

    def test_list_keys(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("alpha", "a")
        ms.save("beta", "b")
        keys = ms.list_keys()
        assert "alpha" in keys
        assert "beta" in keys

    def test_delete(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("temp", "delete me")
        assert ms.delete("temp") is True
        assert ms.load("temp") is None

    def test_delete_nonexistent(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        assert ms.delete("nope") is False

    def test_case_insensitive_search(self, tmp_path):
        ms = MemoryStore(str(tmp_path / "memory"))
        ms.save("note", "Python is GREAT")
        result = ms.search("python")
        assert "GREAT" in result
        result2 = ms.search("PYTHON")
        assert "GREAT" in result2
