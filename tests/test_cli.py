"""Tests for taui.cli — arg parsing and REPL mechanics."""

from taui.cli import parse_args, Repl


class TestParseArgs:
    def test_no_args(self):
        result = parse_args([])
        assert result == {}

    def test_provider(self):
        result = parse_args(["-p", "codex"])
        assert result["provider"] == "codex"

    def test_model(self):
        result = parse_args(["-m", "gpt-4o"])
        assert result["model"] == "gpt-4o"

    def test_dir(self):
        result = parse_args(["-d", "/tmp"])
        assert str(result["working_dir"]).startswith("/")

    def test_initial_message(self):
        result = parse_args(["hello", "world"])
        assert result["initial_message"] == "hello world"

    def test_combined(self):
        result = parse_args(["-p", "copilot", "-m", "claude-sonnet-4-20250514", "fix the bug"])
        assert result["provider"] == "copilot"
        assert result["model"] == "claude-sonnet-4-20250514"
        assert result["initial_message"] == "fix the bug"

    def test_long_form(self):
        result = parse_args(["--provider", "codex", "--model", "o3-mini"])
        assert result["provider"] == "codex"
        assert result["model"] == "o3-mini"

    def test_web_flag(self):
        result = parse_args(["--web"])
        assert result["mode"] == "web"

    def test_tui_flag(self):
        result = parse_args(["--tui"])
        assert result["mode"] == "tui"

    def test_web_takes_precedence_over_tui(self):
        result = parse_args(["--web", "--tui"])
        assert result["mode"] == "web"

    def test_no_mode_by_default(self):
        result = parse_args([])
        assert "mode" not in result
