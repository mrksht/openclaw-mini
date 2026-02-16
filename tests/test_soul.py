"""Tests for SOUL loading and system prompt building."""

import os
import tempfile

from openclaw.agent.soul import DEFAULT_SOUL, build_system_prompt, load_soul


class TestLoadSoul:
    """SOUL.md loading."""

    def test_load_from_file(self, tmp_path):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Custom Agent\nBe awesome.")
        assert load_soul(str(soul_file)) == "# Custom Agent\nBe awesome."

    def test_fallback_on_missing_file(self):
        result = load_soul("/nonexistent/SOUL.md")
        assert result == DEFAULT_SOUL

    def test_fallback_on_none(self):
        assert load_soul(None) == DEFAULT_SOUL

    def test_fallback_on_empty_file(self, tmp_path):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("   \n  ")
        assert load_soul(str(soul_file)) == DEFAULT_SOUL

    def test_unicode_soul(self, tmp_path):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# エージェント\n日本語で応答してください 🤖")
        result = load_soul(str(soul_file))
        assert "エージェント" in result


class TestBuildSystemPrompt:
    """System prompt construction."""

    def test_soul_is_included(self):
        prompt = build_system_prompt("Be helpful.")
        assert "Be helpful." in prompt

    def test_date_is_included(self):
        prompt = build_system_prompt("soul")
        assert "Current date:" in prompt

    def test_workspace_included(self):
        prompt = build_system_prompt("soul", workspace_path="/home/user/.openclaw")
        assert "/home/user/.openclaw" in prompt

    def test_workspace_omitted_when_none(self):
        prompt = build_system_prompt("soul", workspace_path=None)
        assert "Workspace:" not in prompt

    def test_extra_context_appended(self):
        prompt = build_system_prompt("soul", extra_context="You have 3 tools available.")
        assert "You have 3 tools available." in prompt

    def test_extra_context_omitted_when_none(self):
        prompt = build_system_prompt("soul", extra_context=None)
        # Should not have empty trailing sections
        assert prompt.endswith(prompt.rstrip())
