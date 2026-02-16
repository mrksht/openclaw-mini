"""Tests for context window compaction."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openclaw.session.compaction import (
    _format_for_summary,
    _split_messages,
    compact,
    estimate_tokens,
)


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0  # "[]" = 2 chars → 0 tokens

    def test_single_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        tokens = estimate_tokens(msgs)
        assert tokens > 0
        # Rough check: JSON is ~40 chars → ~10 tokens
        assert tokens < 50

    def test_scales_with_content(self):
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "x" * 4000}]
        assert estimate_tokens(long) > estimate_tokens(short) * 10


class TestSplitMessages:
    def test_even_split(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
        ]
        old, recent = _split_messages(msgs)
        assert len(old) + len(recent) == len(msgs)
        # Recent half should start with a user message
        assert recent[0]["role"] == "user"

    def test_single_message(self):
        msgs = [{"role": "user", "content": "only"}]
        old, recent = _split_messages(msgs)
        assert len(old) + len(recent) == 1

    def test_preserves_all_messages(self):
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        old, recent = _split_messages(msgs)
        all_back = old + recent
        assert all_back == msgs

    def test_splits_on_user_boundary(self):
        msgs = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "t"}}]},
            {"role": "tool", "content": "result"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        old, recent = _split_messages(msgs)
        # Should not split in the middle of a tool sequence
        assert recent[0]["role"] == "user"


class TestFormatForSummary:
    def test_text_messages(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _format_for_summary(msgs)
        assert "User: Hello" in result
        assert "Assistant: Hi there" in result

    def test_tool_calls(self):
        msgs = [
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "run_command"}},
            ]},
        ]
        result = _format_for_summary(msgs)
        assert "run_command" in result

    def test_tool_result(self):
        msgs = [
            {"role": "tool", "tool_call_id": "c1", "content": "file contents here"},
        ]
        result = _format_for_summary(msgs)
        assert "file contents" in result
        assert "c1" in result


class TestCompact:
    def test_noop_under_threshold(self):
        msgs = [{"role": "user", "content": "short"}]
        client = MagicMock()
        result = compact(msgs, client, "model", threshold=100_000)
        assert result == msgs
        client.chat.completions.create.assert_not_called()

    def test_compacts_over_threshold(self):
        # Create messages that exceed a low threshold
        msgs = [
            {"role": "user", "content": f"message {i}" * 20}
            for i in range(20)
        ]

        # Mock the summarization response
        summary_response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="• User sent 10 messages about various topics")
            )]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = summary_response

        result = compact(msgs, client, "test-model", threshold=50)

        # Should have compacted
        assert len(result) < len(msgs)
        # First message should be the summary
        assert "[Conversation summary" in result[0]["content"]
        # Should have called the LLM once for summarization
        client.chat.completions.create.assert_called_once()

    def test_summary_contains_old_count(self):
        msgs = [
            {"role": "user", "content": f"msg {i}" * 50}
            for i in range(10)
        ]

        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Summary of old messages")
            )]
        )

        result = compact(msgs, client, "m", threshold=10)
        summary_msg = result[0]
        assert "earlier messages" in summary_msg["content"]

    def test_preserves_recent_messages(self):
        msgs = [
            {"role": "user", "content": f"old-{i}" * 50}
            for i in range(6)
        ] + [
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
        ]

        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Summary")
            )]
        )

        result = compact(msgs, client, "m", threshold=10)
        contents = [m.get("content", "") for m in result]
        # Recent messages must be preserved
        assert "recent question" in contents
        assert "recent answer" in contents

    def test_empty_summary_fallback(self):
        msgs = [{"role": "user", "content": "x" * 5000} for _ in range(4)]

        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=None)
            )]
        )

        result = compact(msgs, client, "m", threshold=10)
        assert "(empty summary)" in result[0]["content"]
