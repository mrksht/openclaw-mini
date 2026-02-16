"""Tests for multi-agent routing."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openclaw.agent.router import AgentConfig, AgentRouter
from openclaw.session.store import SessionStore
from openclaw.tools.registry import Tool, ToolRegistry


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(str(tmp_path / "sessions"))


@pytest.fixture
def tool_registry():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="Echo input",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=lambda inp: f"echoed: {inp['text']}",
        )
    )
    return registry


def _make_response(content="OK"):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


class TestAgentConfig:
    def test_default_soul(self):
        """AgentConfig with no soul_path uses built-in default."""
        config = AgentConfig(name="Test", model="m")
        soul = config.soul
        assert len(soul) > 0
        assert "Assistant" in soul  # From DEFAULT_SOUL

    def test_system_prompt_includes_soul(self):
        config = AgentConfig(name="Test", model="m")
        prompt = config.system_prompt
        assert "Assistant" in prompt

    def test_custom_soul(self, tmp_path):
        soul_file = tmp_path / "custom.md"
        soul_file.write_text("I am a custom agent")
        config = AgentConfig(name="Custom", model="m", soul_path=str(soul_file))
        assert "custom agent" in config.soul

    def test_workspace_in_prompt(self):
        config = AgentConfig(name="Test", model="m", workspace_path="/my/workspace")
        assert "/my/workspace" in config.system_prompt


class TestAgentRouter:
    def test_resolve_default(self):
        default = AgentConfig(name="Jarvis", model="m")
        router = AgentRouter(default_agent=default)

        agent, text = router.resolve("Hello world")
        assert agent.name == "Jarvis"
        assert text == "Hello world"

    def test_resolve_prefix(self):
        default = AgentConfig(name="Jarvis", model="m")
        research = AgentConfig(name="Scout", model="m", prefix="/research",
                               session_prefix="agent:research")
        router = AgentRouter(default_agent=default, agents=[research])

        agent, text = router.resolve("/research quantum computing")
        assert agent.name == "Scout"
        assert text == "quantum computing"

    def test_resolve_prefix_case_insensitive(self):
        default = AgentConfig(name="Jarvis", model="m")
        research = AgentConfig(name="Scout", model="m", prefix="/research")
        router = AgentRouter(default_agent=default, agents=[research])

        agent, text = router.resolve("/RESEARCH big question")
        assert agent.name == "Scout"
        assert text == "big question"

    def test_resolve_prefix_no_query(self):
        default = AgentConfig(name="Jarvis", model="m")
        research = AgentConfig(name="Scout", model="m", prefix="/research")
        router = AgentRouter(default_agent=default, agents=[research])

        agent, text = router.resolve("/research")
        assert agent.name == "Scout"
        assert text == "(no query provided)"

    def test_resolve_unknown_prefix_goes_to_default(self):
        default = AgentConfig(name="Jarvis", model="m")
        router = AgentRouter(default_agent=default)

        agent, text = router.resolve("/unknown command")
        assert agent.name == "Jarvis"
        assert text == "/unknown command"

    def test_agent_names(self):
        default = AgentConfig(name="Jarvis", model="m")
        scout = AgentConfig(name="Scout", model="m", prefix="/research")
        router = AgentRouter(default_agent=default, agents=[scout])

        assert "Jarvis" in router.agent_names
        assert "Scout" in router.agent_names

    def test_prefixes(self):
        default = AgentConfig(name="Jarvis", model="m")
        scout = AgentConfig(name="Scout", model="m", prefix="/research")
        router = AgentRouter(default_agent=default, agents=[scout])

        assert "/research" in router.prefixes

    def test_run_routes_to_correct_agent(self, session_store, tool_registry):
        """Router.run() dispatches to the correct agent and builds session key."""
        default = AgentConfig(name="Jarvis", model="default-model",
                              session_prefix="agent:main")
        scout = AgentConfig(name="Scout", model="scout-model",
                            prefix="/research", session_prefix="agent:research")
        router = AgentRouter(default_agent=default, agents=[scout])

        client = MagicMock()
        client.chat.completions.create.return_value = _make_response("Research result")

        result = router.run(
            client=client,
            user_text="/research AI safety",
            channel="repl",
            user_id="user1",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "Research result"
        # Verify the correct model was used
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "scout-model"

    def test_run_default_agent(self, session_store, tool_registry):
        default = AgentConfig(name="Jarvis", model="jarvis-model",
                              session_prefix="agent:main")
        router = AgentRouter(default_agent=default)

        client = MagicMock()
        client.chat.completions.create.return_value = _make_response("Hello!")

        result = router.run(
            client=client,
            user_text="Hi there",
            channel="repl",
            user_id="user1",
            session_store=session_store,
            tool_registry=tool_registry,
        )

        assert result == "Hello!"
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "jarvis-model"

    def test_session_isolation(self, session_store, tool_registry):
        """Different agents get different session keys."""
        default = AgentConfig(name="Jarvis", model="m", session_prefix="agent:main")
        scout = AgentConfig(name="Scout", model="m", prefix="/research",
                            session_prefix="agent:research")
        router = AgentRouter(default_agent=default, agents=[scout])

        client = MagicMock()
        client.chat.completions.create.return_value = _make_response("ok")

        # Send to default
        router.run(client=client, user_text="hello", channel="repl",
                    user_id="u1", session_store=session_store,
                    tool_registry=tool_registry)

        # Send to research
        router.run(client=client, user_text="/research topic", channel="repl",
                    user_id="u1", session_store=session_store,
                    tool_registry=tool_registry)

        # Check that different session keys were used
        sessions = session_store.list_sessions()
        assert len(sessions) == 2
        prefixes = {s.split(":")[1] if ":" in s else s for s in sessions}
        # Should have sessions for both "main" and "research"
        assert len(prefixes) >= 2
