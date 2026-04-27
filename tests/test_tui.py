"""Tests for taui.tui module — import and structure tests (no live app)."""

from __future__ import annotations

import pytest

from taui.tui import TauiApp, run_tui, _trunc


class TestTrunc:
    def test_short_string(self):
        assert _trunc("hello", 10) == "hello"

    def test_exact_length(self):
        assert _trunc("hello", 5) == "hello"

    def test_long_string(self):
        result = _trunc("a" * 50, 20)
        assert len(result) == 20
        assert result.endswith("...")

    def test_default_length(self):
        assert _trunc("short") == "short"


class TestTauiApp:
    def test_instantiate(self):
        app = TauiApp()
        assert app.TITLE == "taui"
        assert app._session is None
        assert app._busy is False

    def test_bindings(self):
        app = TauiApp()
        keys = [b[0] if isinstance(b, tuple) else b.key for b in app.BINDINGS]
        assert "ctrl+c" in keys
        assert "ctrl+l" in keys

    def test_run_tui_is_callable(self):
        assert callable(run_tui)
