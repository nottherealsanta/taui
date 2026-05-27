"""Tests for taui.main."""

from __future__ import annotations


def test_parse_args_session():
    from taui.main import parse_args

    assert parse_args(["--session", "abc123"]) == {"session_id": "abc123"}


def test_main_prints_resume_hint(monkeypatch, capsys):
    from taui import main as main_module

    monkeypatch.setattr(main_module, "_setup_logging", lambda: None)

    def fake_run_tui(config, **kwargs):
        assert config.session_id == "abc123"
        assert kwargs == {"debug": False, "debug_socket": None}
        return "abc123"

    import taui.tui

    monkeypatch.setattr(taui.tui, "run_tui", fake_run_tui)
    main_module.main(["-p", "copilot", "--session", "abc123"])

    output = capsys.readouterr().out
    assert "to continue session run: uv run taui --session abc123" in output


def test_main_skips_resume_hint_for_unpersisted_session(monkeypatch, capsys):
    from taui import main as main_module

    monkeypatch.setattr(main_module, "_setup_logging", lambda: None)

    def fake_run_tui(config, **kwargs):
        return None

    import taui.tui

    monkeypatch.setattr(taui.tui, "run_tui", fake_run_tui)
    main_module.main(["-p", "copilot"])

    output = capsys.readouterr().out
    assert "to continue session run:" not in output
