"""TUI interaction scenarios — non-snapshot behavior tests.

These complement the visual snapshots: they assert on widget state and
internal app state after specific user actions. If a snapshot ever drifts
unexpectedly, these tests narrow down which behavior actually broke.

All tests drive the real `TauiApp` through `app.run_test()` with the
scripted-provider patch from `tests.scenarios.tui_harness`.
"""

from __future__ import annotations

import asyncio

from textual.containers import VerticalScroll
from textual.widgets import Static

from tests.scenarios import ScriptedProvider, Turn, scenarios
from tests.scenarios.tui_harness import use_scripted_provider


async def _ready(app, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if app._session is not None and not app._session_initializing:
            return
        await asyncio.sleep(0)
    raise TimeoutError("session never ready")


async def _wait_idle(app, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if not getattr(app, "_is_processing", False):
            return
        await asyncio.sleep(0)
    raise TimeoutError("app stayed busy")


class TestSlashCommands:
    async def test_clear_removes_chat_log_children(self, tmp_path, monkeypatch):
        provider = scenarios.streamed_reply("first reply")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            from taui.tui.widgets.chat_input import ChatInput

            chat_input = app.query_one("#chat-input", ChatInput)
            chat_input.text = "hello"
            chat_input.focus()
            await pilot.press("enter")
            await _wait_idle(app)

            chat_log = app.query_one("#chat-log", VerticalScroll)
            assert len(chat_log.children) > 0

            chat_input.text = "/clear"
            await pilot.press("enter")
            await pilot.pause()

            assert len(chat_log.children) == 0
            await app._session.close()

    async def test_help_command_shows_listing(self, tmp_path, monkeypatch):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            from taui.tui.widgets.chat_input import ChatInput

            chat_input = app.query_one("#chat-input", ChatInput)
            chat_input.text = "/help"
            chat_input.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Look for command names in the rendered chat log statics
            rendered = " ".join(str(w.content) for w in app.query(Static))
            assert "/clear" in rendered
            assert "/help" in rendered or "Get help" in rendered
            await app._session.close()


class TestErrorRendering:
    async def test_auth_expired_shows_error_in_log(self, tmp_path, monkeypatch):
        provider = scenarios.auth_expired()
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            from taui.tui.widgets.chat_input import ChatInput

            chat_input = app.query_one("#chat-input", ChatInput)
            chat_input.text = "hi"
            chat_input.focus()
            await pilot.press("enter")
            await _wait_idle(app, timeout=3.0)

            rendered = " ".join(str(w.content) for w in app.query(Static))
            assert "token expired" in rendered.lower() or "error" in rendered.lower()
            # And processing should be cleared
            assert not app._is_processing
            await app._session.close()


class TestQueueWhileBusy:
    async def test_queue_flag_appends_to_pending(self, tmp_path, monkeypatch):
        """When a Submitted message arrives with queue=True, it's appended to _queued.

        We test the queue routing in isolation rather than racing the agent loop
        — the timing of the busy window is too fine-grained to assert on without
        explicit synchronization, but the routing itself is deterministic.
        """
        provider = scenarios.happy_path("ok")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            from taui.tui.widgets.chat_input import ChatInput

            # Force the busy state and post a queued-style message directly.
            app._is_processing = True
            assert app._queued == []
            app.post_message(ChatInput.Submitted("queued message", queue=True))
            await pilot.pause()
            # The app stores queued items as (text, images_or_None) tuples.
            queued_texts = [item[0] if isinstance(item, tuple) else item for item in app._queued]
            assert "queued message" in queued_texts

            app._is_processing = False
            await app._session.close()


class TestStartupError:
    async def test_session_create_failure_shows_red_message(self, tmp_path, monkeypatch):
        """If Session.create raises, the app should display the failure inline."""
        import taui.session as session_module

        async def broken_create_provider(_c):
            raise RuntimeError("simulated provider auth failure")

        monkeypatch.setattr(session_module, "_create_provider", broken_create_provider)

        from taui.config import Config
        from taui.tui import TauiApp

        app = TauiApp(Config(working_dir=tmp_path))
        async with app.run_test() as pilot:
            # Wait for the session-init worker to finish
            deadline = asyncio.get_event_loop().time() + 2.0
            while (
                asyncio.get_event_loop().time() < deadline
                and app._session_initializing
            ):
                await pilot.pause()
            rendered = " ".join(str(w.content) for w in app.query(Static))
            assert "Could not start session" in rendered
            assert "simulated provider auth failure" in rendered
