"""Tests for taui.main."""

from __future__ import annotations


def test_parse_args_session():
    from taui.main import parse_args

    assert parse_args(["--session", "abc123"]) == {"session_id": "abc123"}


def test_main_prints_resume_hint(monkeypatch, capsys):
    from taui import main as main_module

    monkeypatch.setattr(main_module, "_setup_logging", lambda: None)
    monkeypatch.setattr(main_module, "_detect_uvx_launcher", lambda: None)

    def fake_run_tui(config, **kwargs):
        assert config.session_id == "abc123"
        assert kwargs == {"debug": False, "debug_socket": None}
        return "abc123"

    import taui.tui

    monkeypatch.setattr(taui.tui, "run_tui", fake_run_tui)
    main_module.main(["-p", "copilot", "--session", "abc123"])

    output = capsys.readouterr().out
    assert "to continue session run: uv run taui --session abc123" in output


def test_main_prints_uvx_resume_hint(monkeypatch, capsys):
    from taui import main as main_module

    monkeypatch.setattr(main_module, "_setup_logging", lambda: None)
    monkeypatch.setattr(main_module, "_detect_uvx_launcher", lambda: "uvx taui@latest")

    def fake_run_tui(config, **kwargs):
        return "abc123"

    import taui.tui

    monkeypatch.setattr(taui.tui, "run_tui", fake_run_tui)
    main_module.main(["-p", "copilot", "--session", "abc123"])

    output = capsys.readouterr().out
    assert "to continue session run: uvx taui@latest --session abc123" in output


def test_build_resume_command():
    from taui.main import _build_resume_command

    assert (
        _build_resume_command("uv run taui", "abc123")
        == "uv run taui --session abc123"
    )
    assert (
        _build_resume_command("uvx taui", "abc123")
        == "uvx taui --session abc123"
    )


def test_parse_uvx_launcher_simple():
    from taui.main import _parse_uvx_launcher

    assert _parse_uvx_launcher(["uvx", "taui"]) == "uvx taui"
    assert _parse_uvx_launcher(["/usr/bin/uvx", "taui"]) == "uvx taui"


def test_parse_uvx_launcher_at_latest():
    from taui.main import _parse_uvx_launcher

    assert _parse_uvx_launcher(["uvx", "taui@latest"]) == "uvx taui@latest"


def test_parse_uvx_launcher_uv_tool_normalized():
    from taui.main import _parse_uvx_launcher

    assert (
        _parse_uvx_launcher(["uv", "tool", "uvx", "taui@latest"])
        == "uvx taui@latest"
    )
    assert _parse_uvx_launcher(["uv", "tool", "uvx", "taui"]) == "uvx taui"


def test_parse_uvx_launcher_unrelated():
    from taui.main import _parse_uvx_launcher

    assert _parse_uvx_launcher(["uv", "run", "taui"]) is None
    assert _parse_uvx_launcher(["uvx", "other-tool"]) is None
    assert _parse_uvx_launcher(["uvx", "taui-extra"]) is None
    assert _parse_uvx_launcher(["bash", "-c", "taui"]) is None
    assert _parse_uvx_launcher([]) is None
    assert _parse_uvx_launcher(["uvx"]) is None


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
