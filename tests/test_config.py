"""Tests for taui.config."""

from pathlib import Path

from taui.config import Config, DEFAULT_SYSTEM_PROMPT


class TestConfig:
    def test_defaults(self):
        cfg = Config.load()
        assert cfg.provider == "copilot"
        assert cfg.model == "claude-haiku-4.5"
        assert cfg.max_turns == 50
        assert cfg.system_prompt == DEFAULT_SYSTEM_PROMPT

    def test_overrides(self):
        cfg = Config(provider="codex", model="gpt-4o", max_turns=10)
        assert cfg.provider == "codex"
        assert cfg.model == "gpt-4o"
        assert cfg.max_turns == 10

    def test_load_with_overrides(self):
        cfg = Config.load(provider="codex", model="o3-mini")
        assert cfg.provider == "codex"
        assert cfg.model == "o3-mini"

    def test_load_none_overrides_ignored(self):
        cfg = Config.load(provider=None, model=None)
        assert cfg.provider == "copilot"  # default

    def test_working_dir_default(self):
        cfg = Config()
        assert cfg.working_dir == Path.cwd()
