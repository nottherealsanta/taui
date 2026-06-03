"""Provider auth contract.

Session creation must never block on interactive login: an unauthenticated
launch surfaces ProviderAuthRequired so the TUI can tell the user to run
`taui --login`, instead of silently waiting on a device-flow prompt the user
cannot see. The `taui --login` path stays interactive.

HOME is isolated to an empty fake home by the global conftest fixture, so no
provider has saved credentials here.
"""

from __future__ import annotations

import pytest

from taui.llm_provider import registry
from taui.llm_provider.auth import ProviderAuthRequired, codex, copilot


class TestNonInteractiveSessionAuth:
    def test_create_provider_copilot_unauthenticated_raises(self, monkeypatch):
        called = {"login": False}
        monkeypatch.setattr(
            copilot, "login", lambda *a, **k: called.__setitem__("login", True)
        )
        with pytest.raises(ProviderAuthRequired) as exc:
            registry.create_provider("copilot")
        assert exc.value.provider == "copilot"
        # Crucially, the interactive device flow was never started.
        assert called["login"] is False

    def test_create_provider_codex_unauthenticated_raises(self, monkeypatch):
        called = {"login": False}
        monkeypatch.setattr(
            codex, "login", lambda *a, **k: called.__setitem__("login", True)
        )
        with pytest.raises(ProviderAuthRequired) as exc:
            registry.create_provider("codex")
        assert exc.value.provider == "codex"
        assert called["login"] is False

    def test_get_copilot_credentials_non_interactive_raises(self):
        with pytest.raises(ProviderAuthRequired):
            copilot.get_copilot_credentials(interactive=False)

    def test_get_codex_credentials_non_interactive_raises(self):
        with pytest.raises(ProviderAuthRequired):
            codex.get_codex_credentials(interactive=False)

    def test_interactive_path_still_calls_login(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(copilot, "login", lambda *a, **k: sentinel)
        assert copilot.get_copilot_credentials(interactive=True) is sentinel


class TestAuthBackwardCompat:
    def test_create_provider_accepts_zero_arg_auth(self):
        """Extension providers whose auth() takes no args keep working."""
        sentinel = object()
        registry.register_provider(
            "zeroarg_test",
            label="Zero Arg",
            factory=lambda creds: creds,
            auth=lambda: sentinel,
            default_model="m",
        )
        try:
            assert registry.create_provider("zeroarg_test") is sentinel
            assert registry.create_provider("zeroarg_test", interactive=True) is sentinel
        finally:
            registry._REGISTRY.pop("zeroarg_test", None)
