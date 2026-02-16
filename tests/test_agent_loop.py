"""Tests for the agent loop with mocked LLM responses."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openclaw.agent.loop import _sanitize_loaded_messages, run_agent_turn
from openclaw.session.store import SessionStore
from openclaw.tools.registry import Tool, ToolRegistry


def _make_response(content=None, tool_calls=None, finish_reason="stop"):
    """Build a mock OpenAI-compatible chat completion response."""
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice])


def _make_tool_call(call_id, name, arguments):
    """Build a mock tool call object."""
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(str(tmp_path / "sessions"))


@pytest.fixture
def tool_registry():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="Echo the input",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda inp: f"echoed: {inp['text']}",
        )
    )
    registry.register(
        Tool(
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            handler=lambda inp: str(inp["a"] + inp["b"]),
        )
    )
    return registry


class TestAgentLoopTextOnly:
    """Agent responds with text, no tool use."""

    def test_simple_text_response(self, session_store, tool_registry):
        client = MagicMock()
        client.chat.completions.create.return_value = _make_response(
            content="Hello! How can I help?"
        )

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Be helpful.",
            session_key="test",
            user_text="Hi",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "Hello! How can I help?"
        # Verify session was persisted
        messages = session_store.load("test")
        assert len(messages) == 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_empty_response(self, session_store, tool_registry):
        client = MagicMock()
        client.chat.completions.create.return_value = _make_response(content=None)

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Be helpful.",
            session_key="test",
            user_text="Hi",
            session_store=session_store,
            tool_registry=tool_registry,
        )
        assert result == ""


class TestAgentLoopToolUse:
    """Agent uses tools then responds."""

    def test_single_tool_call(self, session_store, tool_registry):
        client = MagicMock()
        # First call: model wants to use echo tool
        # Second call: model responds with text after seeing tool result
        client.chat.completions.create.side_effect = [
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("call_1", "echo", {"text": "hello"})],
                finish_reason="tool_use",  # Anthropic via Portkey uses "tool_use"
            ),
            _make_response(content="The echo said: hello"),
        ]

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Use tools.",
            session_key="test",
            user_text="Echo hello",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "The echo said: hello"
        assert client.chat.completions.create.call_count == 2

        # Check session has all messages
        messages = session_store.load("test")
        assert len(messages) == 4  # user, assistant(tool_call), tool_result, assistant(text)
        assert messages[0]["role"] == "user"
        assert "tool_calls" in messages[1]
        assert messages[2]["role"] == "tool"
        assert messages[3]["role"] == "assistant"

    def test_multi_tool_chain(self, session_store, tool_registry):
        """Model calls one tool, then another, then responds."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            # First: call echo
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("c1", "echo", {"text": "x"})],
                finish_reason="tool_use",
            ),
            # Second: call add
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("c2", "add", {"a": 2, "b": 3})],
                finish_reason="tool_use",
            ),
            # Third: final text
            _make_response(content="Echo said x, sum is 5"),
        ]

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Use tools.",
            session_key="test",
            user_text="Do stuff",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "Echo said x, sum is 5"
        assert client.chat.completions.create.call_count == 3

    def test_parallel_tool_calls(self, session_store, tool_registry):
        """Model calls multiple tools in one response."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(
                content=None,
                tool_calls=[
                    _make_tool_call("c1", "echo", {"text": "a"}),
                    _make_tool_call("c2", "add", {"a": 1, "b": 2}),
                ],
                finish_reason="tool_use",
            ),
            _make_response(content="Done both"),
        ]

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Use tools.",
            session_key="test",
            user_text="Do two things",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "Done both"
        # Should have: user, assistant(2 tool_calls), tool_result_1, tool_result_2, assistant
        messages = session_store.load("test")
        assert len(messages) == 5


class TestAgentLoopEdgeCases:
    """Edge cases and safety."""

    def test_max_turns_limit(self, session_store, tool_registry):
        """Agent stops after max_turns to prevent infinite loops."""
        client = MagicMock()
        # Always return tool calls — never stops
        client.chat.completions.create.return_value = _make_response(
            content=None,
            tool_calls=[_make_tool_call("c1", "echo", {"text": "loop"})],
            finish_reason="tool_use",
        )

        result = run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Loop forever.",
            session_key="test",
            user_text="Go",
            session_store=session_store,
            tool_registry=tool_registry,
            max_turns=3,
        )

        assert result == "(max tool turns reached)"
        assert client.chat.completions.create.call_count == 3

    def test_on_tool_use_callback(self, session_store, tool_registry):
        """Callback is called for each tool execution."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("c1", "echo", {"text": "cb"})],
                finish_reason="tool_use",
            ),
            _make_response(content="Done"),
        ]

        calls = []

        def on_tool(name, inp, result):
            calls.append((name, inp, result))

        run_agent_turn(
            client=client,
            model="test-model",
            system_prompt="Test.",
            session_key="test",
            user_text="Go",
            session_store=session_store,
            tool_registry=tool_registry,
            on_tool_use=on_tool,
        )

        assert len(calls) == 1
        assert calls[0] == ("echo", {"text": "cb"}, "echoed: cb")

    def test_session_continuity(self, session_store, tool_registry):
        """Multiple turns share the same session."""
        client = MagicMock()
        client.chat.completions.create.return_value = _make_response(
            content="I remember."
        )

        # First turn
        run_agent_turn(
            client=client, model="m", system_prompt="s",
            session_key="persist", user_text="My name is Nader",
            session_store=session_store, tool_registry=tool_registry,
        )

        # Second turn — should include previous messages
        run_agent_turn(
            client=client, model="m", system_prompt="s",
            session_key="persist", user_text="What is my name?",
            session_store=session_store, tool_registry=tool_registry,
        )

        # Check the second API call included history
        second_call = client.chat.completions.create.call_args_list[1]
        api_messages = second_call.kwargs["messages"]
        # system + user1 + assistant1 + user2 = 4
        assert len(api_messages) == 4
        assert api_messages[0]["role"] == "system"
        assert api_messages[1]["content"] == "My name is Nader"
        assert api_messages[3]["content"] == "What is my name?"

    def test_tool_calls_finish_reason_openai_format(self, session_store, tool_registry):
        """OpenAI-format finish_reason='tool_calls' should also work."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("c1", "echo", {"text": "compat"})],
                finish_reason="tool_calls",  # OpenAI format
            ),
            _make_response(content="compat done"),
        ]

        result = run_agent_turn(
            client=client, model="m", system_prompt="s",
            session_key="test", user_text="test compat",
            session_store=session_store, tool_registry=tool_registry,
        )

        assert result == "compat done"
        assert client.chat.completions.create.call_count == 2

    def test_unknown_tool_handled(self, session_store, tool_registry):
        """If model calls an unknown tool, it gets an error message back."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(
                content=None,
                tool_calls=[_make_tool_call("c1", "nonexistent", {"x": 1})],
                finish_reason="tool_use",
            ),
            _make_response(content="Tool not found, sorry."),
        ]

        result = run_agent_turn(
            client=client, model="m", system_prompt="s",
            session_key="test", user_text="Use fake tool",
            session_store=session_store, tool_registry=tool_registry,
        )

        assert result == "Tool not found, sorry."
        # The tool result should contain the error
        messages = session_store.load("test")
        tool_msg = [m for m in messages if m.get("role") == "tool"][0]
        assert "Unknown tool" in tool_msg["content"]


class TestSanitizeLoadedMessages:
    """Tests for _sanitize_loaded_messages — orphan cleanup."""

    def test_empty_list(self):
        assert _sanitize_loaded_messages([]) == []

    def test_no_orphans(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert _sanitize_loaded_messages(msgs) == msgs

    def test_strips_trailing_tool_calls(self):
        msgs = [
            {"role": "user", "content": "run ls"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": "{}"}}]},
        ]
        result = _sanitize_loaded_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_keeps_tool_calls_with_results(self):
        msgs = [
            {"role": "user", "content": "run ls"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "file1"},
            {"role": "assistant", "content": "Here are the files"},
        ]
        result = _sanitize_loaded_messages(msgs)
        assert len(result) == 4  # all kept

    def test_strips_multiple_trailing_orphans(self):
        msgs = [
            {"role": "user", "content": "msg"},
            {"role": "assistant", "tool_calls": [{"id": "a"}]},
            {"role": "assistant", "tool_calls": [{"id": "b"}]},
        ]
        result = _sanitize_loaded_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_assistant_without_tool_calls_not_stripped(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "bye"},
        ]
        result = _sanitize_loaded_messages(msgs)
        assert len(result) == 2


class TestOrphanedSessionRecovery:
    """Agent recovers when a previous session has orphaned tool_calls."""

    def test_orphan_session_still_works(self, session_store, tool_registry):
        """Pre-seed session with orphaned tool_calls, verify agent still works."""
        # Simulate the old bug: assistant with tool_calls saved but no tool results
        session_store.append("test", {"role": "user", "content": "run ls"})
        session_store.append("test", {
            "role": "assistant",
            "tool_calls": [{"id": "orphan_1", "type": "function",
                           "function": {"name": "run_command", "arguments": '{"command":"ls"}'}}],
        })

        client = MagicMock()
        client.chat.completions.create.return_value = _make_response(
            content="Sure, how can I help?"
        )

        result = run_agent_turn(
            client=client, model="m", system_prompt="s",
            session_key="test", user_text="hello",
            session_store=session_store, tool_registry=tool_registry,
        )

        assert result == "Sure, how can I help?"
        # The API call should NOT include the orphaned tool_calls message
        call_args = client.chat.completions.create.call_args
        api_messages = call_args.kwargs["messages"]
        tool_call_msgs = [m for m in api_messages if m.get("tool_calls")]
        assert len(tool_call_msgs) == 0
