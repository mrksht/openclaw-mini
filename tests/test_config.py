"""Tests for the configuration system."""

import json
import os

import pytest

from openclaw.config import AgentDef, AppConfig, ChannelDef, HeartbeatDef


class TestAppConfigDefaults:
    def test_default_config(self):
        config = AppConfig()
        assert config.default_model != ""
        assert config.agents == {}
        assert config.channels == {}
        assert config.heartbeats == []
        assert len(config.safe_commands) > 0

    def test_default_safe_commands(self):
        config = AppConfig()
        assert "ls" in config.safe_commands
        assert "git" in config.safe_commands
        assert "python" in config.safe_commands


class TestAppConfigFromDict:
    def test_minimal_config(self):
        config = AppConfig.from_dict({})
        assert config.default_model != ""

    def test_agents(self):
        data = {
            "agents": {
                "main": {"name": "Jarvis", "model": "claude-sonnet"},
                "researcher": {
                    "name": "Scout",
                    "model": "claude-sonnet",
                    "prefix": "/research",
                    "session_prefix": "agent:research",
                },
            }
        }
        config = AppConfig.from_dict(data)
        assert "main" in config.agents
        assert config.agents["main"].name == "Jarvis"
        assert config.agents["researcher"].prefix == "/research"

    def test_channels(self):
        data = {
            "channels": {
                "repl": {"enabled": True},
                "http": {"enabled": True, "port": 8080},
            }
        }
        config = AppConfig.from_dict(data)
        assert config.channels["repl"].enabled is True
        assert config.channels["http"].port == 8080

    def test_heartbeats(self):
        data = {
            "heartbeats": [
                {
                    "name": "morning",
                    "schedule": "every day at 07:30",
                    "prompt": "Good morning!",
                    "agent": "main",
                }
            ]
        }
        config = AppConfig.from_dict(data)
        assert len(config.heartbeats) == 1
        assert config.heartbeats[0].name == "morning"
        assert config.heartbeats[0].agent == "main"

    def test_custom_safe_commands(self):
        data = {"permissions": {"safe_commands": ["ls", "cat"]}}
        config = AppConfig.from_dict(data)
        assert config.safe_commands == ["ls", "cat"]

    def test_custom_model(self):
        data = {"default_model": "@OpenAI/gpt-5"}
        config = AppConfig.from_dict(data)
        assert config.default_model == "@OpenAI/gpt-5"

    def test_workspace_expansion(self):
        data = {"workspace": "~/my-workspace"}
        config = AppConfig.from_dict(data)
        assert "~" not in config.workspace
        assert "my-workspace" in config.workspace


class TestAppConfigFromFile:
    def test_load_existing_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "default_model": "@OpenAI/gpt-5",
            "agents": {"main": {"name": "TestBot"}},
        }))
        config = AppConfig.from_file(str(config_file))
        assert config.default_model == "@OpenAI/gpt-5"
        assert config.agents["main"].name == "TestBot"

    def test_load_missing_file(self):
        config = AppConfig.from_file("/nonexistent/config.json")
        # Should return defaults, not raise
        assert config.default_model != ""

    def test_load_from_workspace(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"default_model": "@Google/gemini-2.5-pro"}))
        config = AppConfig.load(workspace=str(tmp_path))
        assert config.default_model == "@Google/gemini-2.5-pro"


class TestAppConfigValidation:
    def test_valid_config(self):
        config = AppConfig()
        warnings = config.validate()
        assert warnings == []

    def test_missing_model(self):
        config = AppConfig(default_model="")
        warnings = config.validate()
        assert any("default_model" in w for w in warnings)

    def test_missing_soul_path(self):
        config = AppConfig(agents={
            "test": AgentDef(name="Test", soul_path="/nonexistent/soul.md")
        })
        warnings = config.validate()
        assert any("soul_path" in w for w in warnings)

    def test_heartbeat_missing_fields(self):
        config = AppConfig(heartbeats=[
            HeartbeatDef(name="", schedule="every 1 minute", prompt="go"),
            HeartbeatDef(name="test", schedule="", prompt="go"),
            HeartbeatDef(name="test2", schedule="every 1 minute", prompt=""),
        ])
        warnings = config.validate()
        assert len(warnings) == 3


class TestDataclasses:
    def test_agent_def(self):
        agent = AgentDef(name="Test", model="m")
        assert agent.name == "Test"
        assert agent.prefix is None

    def test_channel_def(self):
        ch = ChannelDef(enabled=True, port=3000)
        assert ch.enabled is True
        assert ch.port == 3000

    def test_heartbeat_def(self):
        hb = HeartbeatDef(name="test", schedule="every 1 minute", prompt="go")
        assert hb.agent == "main"


class TestFullConfig:
    def test_round_trip(self, tmp_path):
        """Write a full config, load it, verify all fields."""
        data = {
            "workspace": str(tmp_path / "workspace"),
            "default_model": "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "agents": {
                "main": {"name": "Jarvis", "model": "claude-sonnet"},
                "researcher": {
                    "name": "Scout",
                    "model": "claude-sonnet",
                    "prefix": "/research",
                    "session_prefix": "agent:research",
                },
            },
            "channels": {
                "repl": {"enabled": True},
                "http": {"enabled": True, "port": 5000},
                "telegram": {"enabled": False},
            },
            "heartbeats": [
                {
                    "name": "morning-check",
                    "schedule": "every day at 07:30",
                    "prompt": "Good morning!",
                    "agent": "main",
                }
            ],
            "permissions": {
                "safe_commands": ["ls", "cat", "git", "python"],
            },
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(data))

        config = AppConfig.from_file(str(config_file))

        assert config.default_model == "@Anthropic/eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert len(config.agents) == 2
        assert config.agents["researcher"].prefix == "/research"
        assert config.channels["http"].port == 5000
        assert config.channels["telegram"].enabled is False
        assert len(config.heartbeats) == 1
        assert config.safe_commands == ["ls", "cat", "git", "python"]
        assert config.validate() == []
