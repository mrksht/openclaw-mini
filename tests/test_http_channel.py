"""Tests for the HTTP API channel."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openclaw.agent.router import AgentConfig, AgentRouter
from openclaw.channels.http_api import HttpApiChannel
from openclaw.queue.command_queue import CommandQueue
from openclaw.session.store import SessionStore
from openclaw.tools.registry import ToolRegistry


def _make_response(content="OK"):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(str(tmp_path / "sessions"))


@pytest.fixture
def tool_registry():
    return ToolRegistry()


@pytest.fixture
def router():
    default = AgentConfig(name="Jarvis", model="test-model", session_prefix="agent:main")
    return AgentRouter(default_agent=default)


@pytest.fixture
def channel(router, session_store, tool_registry):
    return HttpApiChannel(
        router=router,
        session_store=session_store,
        tool_registry=tool_registry,
        command_queue=CommandQueue(),
    )


@pytest.fixture
def client(channel):
    """Flask test client."""
    app = channel.app
    app.config["TESTING"] = True
    return app.test_client()


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "Jarvis" in data["agents"]


class TestChatEndpoint:
    @patch("openclaw.channels.http_api.HttpApiChannel._get_client")
    def test_chat_returns_response(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response("Hello!")
        mock_get_client.return_value = mock_client

        resp = client.post("/chat", json={"message": "Hi", "user_id": "u1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["response"] == "Hello!"

    @patch("openclaw.channels.http_api.HttpApiChannel._get_client")
    def test_chat_default_user_id(self, mock_get_client, client):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response("Hi anon")
        mock_get_client.return_value = mock_client

        resp = client.post("/chat", json={"message": "Hello"})
        assert resp.status_code == 200

    def test_chat_missing_message(self, client):
        resp = client.post("/chat", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_chat_empty_message(self, client):
        resp = client.post("/chat", json={"message": ""})
        assert resp.status_code == 400


class TestSessionsEndpoint:
    @patch("openclaw.channels.http_api.HttpApiChannel._get_client")
    def test_list_sessions(self, mock_get_client, client, session_store):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response("ok")
        mock_get_client.return_value = mock_client

        # Create a session via chat
        client.post("/chat", json={"message": "hello", "user_id": "test"})

        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["sessions"]) >= 1
