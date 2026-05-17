"""TauiApp harness for visual snapshot tests.

The cleanest swap point is `taui.session._create_provider` — it's the only
place where `Session.create()` builds a real LLM provider. We monkeypatch
that to hand back a `ScriptedProvider`, so the rest of the wiring (tools,
registry, store, prompt, agent loop) runs through the real code paths.

Usage::

    from tests.scenarios import scenarios
    from tests.scenarios.tui_harness import use_scripted_provider

    def test_idle(snap_compare, tmp_path, monkeypatch):
        provider = scenarios.happy_path("hi")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        assert snap_compare(app)
"""

from __future__ import annotations

from pathlib import Path

from taui.config import Config
from taui.tui import TauiApp

from .scripted_provider import ScriptedProvider


def use_scripted_provider(
    monkeypatch,
    working_dir: Path,
    provider: ScriptedProvider,
    *,
    config: Config | None = None,
) -> TauiApp:
    """Patch Session creation to use `provider`, return a fresh TauiApp.

    The patch is scoped to the test (via monkeypatch), so the moment the
    test function returns it's lifted automatically.
    """
    config = config or Config(
        working_dir=working_dir,
        model="<model_id>",
        provider="<provider_id>",
    )

    async def _fake_create_provider(_config):
        return provider

    monkeypatch.setattr("taui.session._create_provider", _fake_create_provider)
    monkeypatch.setattr("taui.tui.app.DEFAULT_MAX_INPUT_TOKENS", 128_000)
    return TauiApp(config)
