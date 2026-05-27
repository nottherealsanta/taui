"""Tests for taui.tui module — import, structure, and unit tests (no live app)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.css.query import NoMatches
from textual.widgets import Static

from taui.tui import TauiApp, run_tui
from taui.tui.app import _model_completion_matches, _trunc
from taui.tui.messages import (
    StreamTextDelta,
    ToolEnded,
    ToolStarted,
)
from taui.tui.screens.agent_picker import AgentPickerScreen
from taui.tui.screens.context_breakdown import ContextBreakdownScreen
from taui.tui.screens.model_picker import ModelPickerScreen
from taui.tui.screens.session_picker import SessionPickerScreen
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.approval import ApprovalPrompt
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.footer import CustomFooter
from taui.tui.widgets.info_bar import InfoBar
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.spinner import ActivityProgress
from taui.tui.widgets.status_bar import ContextStatus, ModelStatus
from taui.tui.widgets.terminal import TerminalOutput
from taui.tui.widgets.tool_status import ToolStatusWidget

# ── _trunc ────────────────────────────────────────────────────────────


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


# ── TauiApp structure ────────────────────────────────────────────────


class TestTauiApp:
    def test_instantiate(self):
        app = TauiApp()
        assert app.TITLE == "taui"
        assert app._session is None
        assert app._is_processing is False

    def test_bindings(self):
        app = TauiApp()
        keys = [b[0] if isinstance(b, tuple) else b.key for b in app.BINDINGS]
        assert "ctrl+q" in keys
        assert "ctrl+n" in keys
        assert "ctrl+b" in keys
        assert "ctrl+x" in keys
        assert "ctrl+c" in keys
        assert app.COMMAND_PALETTE_BINDING == "ctrl+p"
        assert app.ENABLE_COMMAND_PALETTE is True

    def test_question_notification_suppressed_for_focused_active_session(self, tmp_path):
        from taui.config import Config

        app = TauiApp(Config(working_dir=tmp_path))
        app._window_focused = True
        app.notify = MagicMock()  # type: ignore[method-assign]

        app._notify_user(
            "Question",
            "Pick one",
            kind="question",
            from_active_session=True,
        )

        app.notify.assert_not_called()

    def test_question_notification_toasts_for_focused_background_session(self, tmp_path):
        from taui.config import Config

        app = TauiApp(Config(working_dir=tmp_path))
        app._window_focused = True
        app.notify = MagicMock()  # type: ignore[method-assign]

        app._notify_user(
            "Question",
            "Pick one",
            kind="question",
            from_active_session=False,
        )

        app.notify.assert_called_once_with("Pick one", title="Question", timeout=4.0)

    def test_question_notification_uses_os_when_app_blurred(self, tmp_path):
        from taui.config import Config

        class FakeDriver:
            def __init__(self) -> None:
                self.writes: list[str] = []
                self.flushed = False

            def write(self, value: str) -> None:
                self.writes.append(value)

            def flush(self) -> None:
                self.flushed = True

        driver = FakeDriver()
        app = TauiApp(Config(working_dir=tmp_path))
        app._window_focused = False
        app._driver = driver
        app.notify = MagicMock()  # type: ignore[method-assign]

        app._notify_user(
            "Question",
            "Pick one",
            kind="question",
            from_active_session=True,
        )

        app.notify.assert_not_called()
        assert driver.writes == ["\x1b]777;notify;Question;Pick one\x07"]
        assert driver.flushed is True

    def test_palette_commands_are_slash_commands_only(self, tmp_path):
        from taui.config import Config

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            _model = "claude-haiku-4.5"

        class FakeSession:
            config = FakeConfig()
            _loop = FakeLoop()
            model_name = "claude-haiku-4.5"

        app = TauiApp(Config(working_dir=tmp_path))
        app._session = FakeSession()
        app._commands = app._build_commands()

        commands = list(app._taui_palette_commands())
        titles = [command.title for command in commands]
        # Palette exposes registered slash commands and nothing else —
        # model/agent selection is reached via the info bar badges.
        assert all(t.startswith("/") for t in titles)
        assert "/model" in titles
        assert "/theme" in titles
        assert "Taui: Select model" not in titles
        assert "Taui: Select agent" not in titles

    async def test_apply_selected_model_updates_session(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            _model = "claude-haiku-4.5"
            _messages = []
            agent_id = ""

        class FakeSession:
            config = FakeConfig()
            _loop = FakeLoop()
            model_name = "claude-haiku-4.5"
            provider_name = "copilot"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = MagicMock(total_cost_usd=0.0)
            session_id = "current"
            _store = MagicMock(update_session=AsyncMock())

            async def resume_session(self, session_id: str) -> bool:
                return True

        app = TauiApp(Config(working_dir=tmp_path))
        with patch.object(
            app_module.Session, "create", AsyncMock(return_value=FakeSession())
        ):
            async with app.run_test():
                app._update_status = MagicMock()
                app._apply_selected_model("gpt-5.5")
                assert app._session.config.model == "gpt-5.5"
                assert app._session._loop._model == "gpt-5.5"

    def test_run_tui_is_callable(self):
        assert callable(run_tui)

    def test_run_tui_returns_final_session_id(self):
        import taui.tui as tui_module

        class FakeApp:
            session_id = "abc123"
            resumable_session_id = "abc123"

            def __init__(self, config):
                self.config = config

            def run(self):
                return None

        with patch.object(tui_module, "TauiApp", FakeApp):
            assert run_tui(object()) == "abc123"

    def test_run_tui_skips_unpersisted_session_id(self):
        import taui.tui as tui_module

        class FakeApp:
            session_id = "abc123"
            resumable_session_id = None

            def __init__(self, config):
                self.config = config

            def run(self):
                return None

        with patch.object(tui_module, "TauiApp", FakeApp):
            assert run_tui(object()) is None

    def test_initial_queues_empty(self):
        app = TauiApp()
        assert app._queued == []
        assert app._pending_indicators == []
        assert app._tool_counter == 0
        assert app._pending_tool_keys == {}
        assert app._active_tool_widgets == {}

    def test_history_file_path(self):
        app = TauiApp()
        assert "taui" in str(app._history_file)
        assert "prompt_history" in str(app._history_file)

    def test_smart_scroll_handles_missing_chat_log(self):
        app = TauiApp()
        app.query_one = MagicMock(side_effect=NoMatches("missing"))  # type: ignore[method-assign]
        app._smart_scroll()  # no raise

    async def test_mount_resumes_configured_session(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        class FakeLoop:
            _messages = []

        class FakeTracker:
            total_cost_usd = 0.0

        class FakeSession:
            session_id = "new"
            provider_name = "copilot"
            model_name = "claude-haiku-4.5"
            model_variant = ""
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = FakeTracker()
            replay_items = []
            _loop = FakeLoop()
            _ext_registry = None

            def __init__(self):
                self.resumed: list[str] = []

            def add_config_change_listener(self, callback):
                return None

            async def resume_session(self, session_id: str) -> bool:
                self.resumed.append(session_id)
                self.session_id = session_id
                return True

        fake = FakeSession()
        monkey = patch.object(app_module.Session, "create", AsyncMock(return_value=fake))
        with monkey:
            app = TauiApp(Config(working_dir=tmp_path, session_id="abc123"))
            async with app.run_test():
                assert fake.resumed == ["abc123"]
                assert app.session_id == "abc123"

    async def test_failed_resume_displays_error(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        class FakeSession:
            session_id = "new"
            last_resume_error = "Session not found: abc123"
            provider_name = "copilot"
            model_name = "claude-haiku-4.5"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = MagicMock(total_cost_usd=0.0)
            _loop = MagicMock(_messages=[], agent_id="")

            async def resume_session(self, session_id: str) -> bool:
                return False

        app = TauiApp(Config(working_dir=tmp_path))
        with patch.object(app_module.Session, "create", AsyncMock(return_value=FakeSession())):
            async with app.run_test():
                assert await app._resume_session("abc123") is False
                assert any(
                    "Session not found: abc123" in str(widget.content)
                    for widget in app.query(Static)
                )

    async def test_session_create_failure_displays_startup_error(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        with patch.object(
            app_module.Session,
            "create",
            AsyncMock(side_effect=RuntimeError("network unavailable")),
        ):
            app = TauiApp(Config(working_dir=tmp_path))
            async with app.run_test():
                assert app._session is None
                assert app.query_one("#chat-input", ChatInput).can_submit is True
                assert any(
                    "Could not start session" in str(widget.content)
                    for widget in app.query(Static)
                )

    async def test_mount_does_not_wait_for_session_create(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_create(config):
            started.set()
            await release.wait()
            raise RuntimeError("stopped")

        with patch.object(app_module.Session, "create", AsyncMock(side_effect=slow_create)):
            app = TauiApp(Config(working_dir=tmp_path))
            async with app.run_test():
                await asyncio.wait_for(started.wait(), timeout=1)
                assert app._session is None
                assert app._session_initializing is True
                assert app.query_one("#chat-input", ChatInput).can_submit is True
                release.set()

    async def test_open_session_picker_shows_sidebar(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module
        from taui.tui.widgets.sidebar import Sidebar

        class FakeSession:
            session_id = "current"
            last_resume_error = ""
            replay_items = []
            provider_name = "copilot"
            model_name = "claude-haiku-4.5"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = MagicMock(total_cost_usd=0.0)
            _loop = MagicMock(_messages=[], agent_id="")

            def __init__(self):
                self.resumed: list[str] = []

            async def resume_session(self, session_id: str) -> bool:
                self.resumed.append(session_id)
                self.session_id = session_id
                return True

        app = TauiApp(Config(working_dir=tmp_path))
        fake = FakeSession()
        with patch.object(app_module.Session, "create", AsyncMock(return_value=fake)):
            async with app.run_test():
                sessions = [{"session_id": "abc123"}]
                await app._open_session_picker(sessions)
                sidebar = app.query_one(Sidebar)
                assert sidebar.has_class("visible")
                assert sidebar._active_tab == "sessions"
                assert len(sidebar._sessions) == 1

    async def test_session_picker_accept_resumes(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module
        from taui.tui.widgets.sidebar import Sidebar

        class FakeSession:
            session_id = "current"
            last_resume_error = ""
            replay_items = []
            provider_name = "copilot"
            model_name = "claude-haiku-4.5"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = MagicMock(total_cost_usd=0.0)
            _loop = MagicMock(_messages=[], agent_id="")

            def __init__(self):
                self.resumed: list[str] = []

            async def resume_session(self, session_id: str) -> bool:
                self.resumed.append(session_id)
                self.session_id = session_id
                return True

        app = TauiApp(Config(working_dir=tmp_path))
        fake = FakeSession()
        with patch.object(app_module.Session, "create", AsyncMock(return_value=fake)):
            async with app.run_test():
                app._wire_callbacks = MagicMock()
                app._update_status = MagicMock()
                sessions = [{"session_id": "abc123"}]
                await app._open_session_picker(sessions)
                # Pick the session from the sidebar by posting the
                # message it would emit when a user clicks a row.
                sidebar = app.query_one(Sidebar)
                sidebar.post_message(Sidebar.SessionSelected("abc123"))
                # Give the worker time to run
                await asyncio.sleep(0.1)
                assert fake.resumed == ["abc123"]

    async def test_model_command_refreshes_status(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            _model = "claude-haiku-4.5"
            _messages = []

        class FakeTracker:
            total_cost_usd = 0.0

        class FakeSession:
            session_id = "current"
            config = FakeConfig()
            _loop = FakeLoop()
            provider_name = "copilot"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = FakeTracker()
            _config_change_listeners: list = []

            @property
            def model_name(self):
                return self.config.model

            def add_config_change_listener(self, cb):
                self._config_change_listeners.append(cb)

            def _notify_config_changed(self):
                for cb in self._config_change_listeners:
                    try:
                        cb()
                    except Exception:
                        pass

        fake = FakeSession()
        with patch.object(app_module.Session, "create", AsyncMock(return_value=fake)):
            app = TauiApp(Config(working_dir=tmp_path))
            async with app.run_test():
                app._update_status = MagicMock()  # type: ignore[method-assign]
                await app._handle_command("/model gpt-5.5")

                assert fake.config.model == "gpt-5.5"
                assert fake._loop._model == "gpt-5.5"
                app._update_status.assert_called_once()
                assert not any(
                    "Model set to" in str(widget.content)
                    for widget in app.query(Static)
                )

    def test_apply_selected_model_updates_existing_session(self, tmp_path):
        from taui.config import Config

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            _model = "claude-haiku-4.5"

        class FakeSession:
            config = FakeConfig()
            _loop = FakeLoop()

        app = TauiApp(Config(working_dir=tmp_path))
        app._session = FakeSession()
        app._update_status = MagicMock()  # type: ignore[method-assign]

        app._apply_selected_model("gpt-5.5")

        assert app._session.config.model == "gpt-5.5"
        assert app._session._loop._model == "gpt-5.5"
        app._update_status.assert_called_once()

    async def test_replay_footer_uses_recorded_model(self, tmp_path):
        from taui.config import Config
        from taui.session_replay import ReplayItem
        from taui.tui import app as app_module
        from taui.tui.widgets.reply_footer import ReplyFooter

        class FakeLoop:
            _messages = []
            agent_id = "CURRENT"

        class FakeTracker:
            total_cost_usd = 0.0

        class FakeSession:
            session_id = "current"
            provider_name = "copilot"
            model_name = "current-model"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = FakeTracker()
            replay_items = [
                ReplayItem(kind="user", text="first"),
                ReplayItem(
                    kind="assistant",
                    text="old reply",
                    agent_id="DEF",
                    model="old-model",
                ),
                ReplayItem(kind="user", text="second"),
                ReplayItem(
                    kind="assistant",
                    text="new reply",
                    agent_id="DEF",
                    model="new-model",
                ),
            ]
            _loop = FakeLoop()
            _ext_registry = None

        app = TauiApp(Config(working_dir=tmp_path))
        with patch.object(app_module.Session, "create", AsyncMock(return_value=FakeSession())):
            async with app.run_test():
                await app._render_replay()

                footers = list(app.query(ReplyFooter))
                assert [footer._model for footer in footers] == [
                    "old-model",
                    "new-model",
                ]

    def test_apply_selected_agent_applies_profile(self, tmp_path):
        from taui.config import Config
        from taui.self_edit import AgentProfile
        from taui.tui import app as app_module

        profile = AgentProfile("PLN", "Plan", "plan", "", "", [], None)

        class FakeStore:
            def __init__(self, working_dir):
                pass

            def load_agents(self):
                return {"PLN": profile}

        app = TauiApp(Config(working_dir=tmp_path))
        app._apply_self_edit_profile = MagicMock()  # type: ignore[method-assign]
        app._update_status = MagicMock()  # type: ignore[method-assign]

        with patch.object(app_module, "SelfEditStore", FakeStore):
            app._apply_selected_agent("pln")

        app._apply_self_edit_profile.assert_called_once_with(profile)
        app._update_status.assert_called_once()

    async def test_mount_applies_default_def_agent(self, tmp_path):
        from taui.config import Config
        from taui.cost import CostTracker
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry
        from taui.tui import app as app_module

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            agent_id = "session"
            stream_id = "stream-1"
            _messages = []

        class FakeSession:
            session_id = "current"
            config = FakeConfig()
            _provider = object()
            _registry = ToolRegistry()
            _executor = ToolExecutor(registry=_registry, policy=ToolPolicy())
            _stream = object()
            _loop = FakeLoop()
            _ext_registry = None
            provider_name = "copilot"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = CostTracker()

            @property
            def model_name(self):
                return self.config.model

            def _replace_loop(self, loop):
                self._loop = loop

        fake = FakeSession()
        with patch.object(app_module.Session, "create", AsyncMock(return_value=fake)):
            app = TauiApp(Config(working_dir=tmp_path))
            async with app.run_test():
                assert fake._loop.agent_id == "DEF"
                info_bar = app.query_one(InfoBar)
                assert info_bar._agent_id == "DEF"

    def test_cycle_agent_profile_applies_next_agent(self, tmp_path):
        from taui.config import Config
        from taui.cost import CostTracker
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"
            system_prompt = ""
            max_turns = 50

        class FakeLoop:
            agent_id = "DEF"
            stream_id = "stream-1"
            _messages = []

        class FakeSession:
            config = FakeConfig()
            _provider = object()
            _registry = ToolRegistry()
            _executor = ToolExecutor(registry=_registry, policy=ToolPolicy())
            _stream = object()
            _loop = FakeLoop()
            _system_prompt = ""
            _base_system_prompt = ""
            provider_name = "copilot"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = CostTracker()
            _config_change_listeners: list = []

            def _replace_loop(self, loop):
                self._loop = loop

            def add_config_change_listener(self, cb):
                self._config_change_listeners.append(cb)

            def _notify_config_changed(self):
                for cb in self._config_change_listeners:
                    try:
                        cb()
                    except Exception:
                        pass

        app = TauiApp(Config(working_dir=tmp_path))
        app._session = FakeSession()
        app._update_status = MagicMock()  # type: ignore[method-assign]

        app._cycle_agent_profile()

        assert app._session._loop.agent_id == "PLN"
        app._update_status.assert_called_once()

    async def test_open_session_picker_dismiss_keeps_session(self, tmp_path):
        from taui.config import Config
        from taui.tui import app as app_module
        from taui.tui.widgets.sidebar import Sidebar

        class FakeSession:
            session_id = "current"
            provider_name = "copilot"
            model_name = "claude-haiku-4.5"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = MagicMock(total_cost_usd=0.0)
            _loop = MagicMock(_messages=[], agent_id="")

            async def resume_session(self, session_id: str) -> bool:
                raise AssertionError("resume should not be called")

        app = TauiApp(Config(working_dir=tmp_path))
        with patch.object(app_module.Session, "create", AsyncMock(return_value=FakeSession())):
            async with app.run_test():
                await app._open_session_picker([{"session_id": "abc123"}])
                sidebar = app.query_one(Sidebar)
                # Dismiss without selecting
                sidebar.action_dismiss()
                assert not sidebar.has_class("visible")
                assert app.session_id == "current"

    def test_session_picker_instantiates(self):
        screen = SessionPickerScreen([{"session_id": "abc123"}])
        assert screen is not None

    def test_model_picker_instantiates(self):
        screen = ModelPickerScreen(
            "copilot",
            [{"id": "claude-haiku-4.5", "context": 200000, "reasoning": True}],
            current="claude-haiku-4.5",
        )
        assert screen is not None

    def test_agent_picker_instantiates(self):
        from taui.self_edit import AgentProfile

        screen = AgentPickerScreen(
            [AgentProfile("DEF", "Default", "default", "", "", [], None)],
            current="DEF",
        )
        assert screen is not None


# ── @file expansion ──────────────────────────────────────────────────


class TestFileExpansion:
    def test_expand_existing_file(self, tmp_path):
        from taui.config import Config
        f = tmp_path / "test.txt"
        f.write_text("file content here")
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs(f"@{f.name}")
        # Text files are now lazy: the path stays in the prompt, the
        # contents do not. The model can call the read tool if needed.
        assert result == f"@{f.name}"
        assert "file content here" not in result
        assert images is None

    def test_expand_nonexistent_file(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs("@nonexistent.txt")
        assert result == "@nonexistent.txt"
        assert images is None

    def test_no_expansion_without_at(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs("hello world")
        assert result == "hello world"
        assert images is None

    def test_bare_at_not_expanded(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs("@")
        assert result == "@"
        assert images is None

    def test_expand_image_file(self, tmp_path):
        """@image.png references should produce a data: URL image."""
        import base64

        from taui.config import Config
        img = tmp_path / "screenshot.png"
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "2mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg=="
        )
        img.write_bytes(png_data)
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs("@screenshot.png")
        assert "[Image 1]" in result
        assert images is not None
        assert len(images) == 1
        assert images[0].startswith("data:image/png;base64,")

    def test_expand_mixed_text_and_image(self, tmp_path):
        """@file refs can mix text and image files."""
        import base64

        from taui.config import Config
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        img = tmp_path / "pic.png"
        img.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "2mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg=="
        ))
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result, images = app._expand_file_refs("look @notes.txt and @pic.png")
        # Text path stays as a literal reference; only the image inlines.
        assert "@notes.txt" in result
        assert "[Image 1]" in result
        assert "hello" not in result
        assert images is not None
        assert len(images) == 1


# ── History persistence ──────────────────────────────────────────────


class TestHistoryPersistence:
    def test_save_and_load(self, tmp_path):
        app = TauiApp()
        app._history_file = tmp_path / "test_history"

        # Manually write history file
        app._history_file.parent.mkdir(parents=True, exist_ok=True)
        app._history_file.write_text("first\nsecond\nthird\n")
        app._load_history()
        assert app._history == ["third", "second", "first"]

    def test_empty_history(self, tmp_path):
        app = TauiApp()
        app._history_file = tmp_path / "nonexistent"
        app._load_history()
        assert app._history == []


# ── ChatInput ────────────────────────────────────────────────────────


class TestChatInput:
    def test_submitted_message_has_queue_flag(self):
        msg = ChatInput.Submitted("hello", queue=False)
        assert msg.value == "hello"
        assert msg.queue is False

        msg_q = ChatInput.Submitted("follow up", queue=True)
        assert msg_q.value == "follow up"
        assert msg_q.queue is True

    def test_submitted_message_carries_images(self):
        msg = ChatInput.Submitted("look at this", images=["data:image/png;base64,abc"])
        assert msg.images == ["data:image/png;base64,abc"]

        msg_no_img = ChatInput.Submitted("just text")
        assert msg_no_img.images == []

    def test_attach_and_clear_images(self):
        ci = ChatInput()
        assert ci.pending_image_count == 0
        ci.attach_image("data:image/png;base64,abc")
        assert ci.pending_image_count == 1
        ci.attach_image("data:image/jpeg;base64,def")
        assert ci.pending_image_count == 2
        ci.clear_images()
        assert ci.pending_image_count == 0


class TestEncodeImageFile:
    def test_encode_png(self, tmp_path):
        import base64

        from taui.tui.widgets.chat_input import _encode_image_file
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        result = _encode_image_file(img)
        assert result is not None
        assert result.startswith("data:image/png;base64,")
        # Decode the base64 part to verify round-trip
        b64_part = result.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert decoded == img.read_bytes()

    def test_encode_jpeg(self, tmp_path):
        from taui.tui.widgets.chat_input import _encode_image_file
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        result = _encode_image_file(img)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_encode_nonexistent(self, tmp_path):
        from taui.tui.widgets.chat_input import _encode_image_file
        result = _encode_image_file(tmp_path / "nope.png")
        assert result is None


class TestExtractImagePaths:
    def test_single_image_path(self, tmp_path):
        from taui.tui.widgets.chat_input import _extract_image_paths
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 10)
        images: list[str] = []
        result = _extract_image_paths(str(img), images)
        assert result == "[Image 1]"
        assert len(images) == 1

    def test_no_image_path(self, tmp_path):
        from taui.tui.widgets.chat_input import _extract_image_paths
        images: list[str] = []
        result = _extract_image_paths("hello world", images)
        assert result == "hello world"
        assert len(images) == 0

    def test_quoted_path(self, tmp_path):
        from taui.tui.widgets.chat_input import _extract_image_paths
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 10)
        images: list[str] = []
        result = _extract_image_paths(f'"{img}"', images)
        assert result == "[Image 1]"
        assert len(images) == 1


class TestAttachmentsBar:
    def test_add_and_count(self):
        from taui.tui.widgets.attachments_bar import AttachmentsBar
        bar = AttachmentsBar()
        assert bar.count == 0
        bar._items = []  # ensure clean state
        idx = bar.add("data:image/png;base64,abc")
        assert idx == 0
        assert bar.count == 1
        assert bar.items[0].kind == "image"
        assert bar.items[0].data == "data:image/png;base64,abc"

    def test_remove(self):
        from taui.tui.widgets.attachments_bar import AttachmentsBar
        bar = AttachmentsBar()
        bar._items = []
        bar.add("data:a")
        bar.add("data:b")
        removed = bar.remove(0)
        assert removed is not None
        assert removed.data == "data:a"
        assert removed.kind == "image"
        assert bar.count == 1
        assert bar.items[0].data == "data:b"

    def test_clear_all(self):
        from taui.tui.widgets.attachments_bar import AttachmentsBar
        bar = AttachmentsBar()
        bar._items = []
        bar.add("data:a")
        bar.add("data:b")
        removed = bar.clear_all()
        assert [a.data for a in removed] == ["data:a", "data:b"]
        assert bar.count == 0

    def test_file_kind_and_lookup(self):
        from taui.tui.widgets.attachments_bar import AttachmentsBar
        bar = AttachmentsBar()
        bar._items = []
        bar.add("/tmp/foo.py", kind="file", name="foo.py")
        bar.add("data:img")
        assert bar.find_index(kind="file", data="/tmp/foo.py") == 0
        assert bar.find_index(kind="image", data="data:img") == 1
        assert bar.find_index(kind="file", data="data:img") == -1

    def test_initial_state(self):
        ci = ChatInput()
        assert ci.can_submit is False
        assert ci.agent_busy is False
        assert ci._history_messages == []
        assert ci._history_index == -1

    def test_load_history(self):
        ci = ChatInput()
        ci.load_history(["newest", "older", "oldest"])
        assert ci._history_messages == ["newest", "older", "oldest"]
        assert ci._history_index == -1

    def test_set_completions_defaults_to_accepting_args(self):
        ci = ChatInput()
        ci.set_completions([("ping", "Test command")])

        assert ci._completions == [("ping", "Test command", True)]

    def test_matching_commands_preserves_accepts_args_metadata(self):
        ci = ChatInput()
        ci.set_completions([
            ("new", "Start a new session", False),
            ("model", "Set model", True),
        ])

        assert ci._get_matching_commands("n") == [
            ("new", "Start a new session", False)
        ]

    def test_model_arg_completion_uses_provider_model_prefix(self):
        ci = ChatInput()
        ci.set_model_completer(
            lambda prefix: [
                ("copilot/claude-haiku-4.5", "200k ctx", True),
                ("codex/gpt-5.3-codex", "400k ctx reasoning", True),
            ]
            if prefix == "co"
            else []
        )
        ci.text = "/model co"

        assert ci._model_arg_prefix() == "co"
        assert ci._get_matching_model_args("co") == [
            ("copilot/claude-haiku-4.5", "200k ctx", True),
            ("codex/gpt-5.3-codex", "400k ctx reasoning", True),
        ]

    def test_text_change_refreshes_model_arg_completion(self):
        ci = ChatInput()
        called: list[str] = []
        ci.set_model_completer(lambda prefix: called.append(prefix) or [])
        ci.text = "/model co"

        ci.on_text_area_changed(object())

        assert called == ["co"]

    def test_agents_arg_completion_uses_generic_command_arg_path(self):
        ci = ChatInput()
        ci.set_arg_completer(
            "agents",
            lambda prefix: [("BLD", "Build", False)] if prefix == "B" else [],
        )
        ci.text = "/agents B"

        assert ci._command_arg_prefix() == ("agents", "B")
        assert ci._get_matching_command_args("agents", "B") == [
            ("BLD", "Build", False)
        ]

    def test_no_arg_command_arg_completion_does_not_fill_on_arrow(self, monkeypatch):
        ci = ChatInput()
        ci.set_arg_completer("agents", lambda prefix: [])
        ci.text = "/agents "

        class FakeDropdown:
            current_value = "PLN"
            current_accepts_args = False

        class FakeApp:
            def query_one(self, widget_type):
                return FakeDropdown()

        monkeypatch.setattr(ChatInput, "app", property(lambda self: FakeApp()))
        ci._fill_selected_completion()

        assert ci.text == "/agents "

    async def test_tab_requests_agent_cycle(self):
        ci = ChatInput()
        posted = []

        class FakeEvent:
            key = "tab"

            def prevent_default(self):
                pass

            def stop(self):
                pass

        ci.post_message = posted.append  # type: ignore[method-assign]
        await ci._on_key(FakeEvent())

        assert isinstance(posted[0], ChatInput.AgentCycleRequested)

    async def test_enter_handled_when_approval_panel_is_active(self, monkeypatch):
        from taui.tui.widgets.info2 import Info2, Info2Mode

        ci = ChatInput()
        ci.can_submit = True
        ci.text = "do not submit"
        calls: list[str] = []

        class FakeInfo2:
            is_active = True
            mode = Info2Mode.APPROVAL

            def accept(self):
                calls.append("accept")

        class FakeApp:
            def query_one(self, widget_type):
                assert widget_type is Info2
                return FakeInfo2()

        class FakeEvent:
            key = "enter"

            def prevent_default(self):
                calls.append("prevent_default")

            def stop(self):
                calls.append("stop")

        ci.post_message = calls.append  # type: ignore[method-assign]
        monkeypatch.setattr(ChatInput, "app", property(lambda self: FakeApp()))

        await ci._on_key(FakeEvent())

        assert "stop" in calls
        assert "prevent_default" in calls
        assert "accept" in calls
        assert ci.text == "do not submit"

    def test_model_completion_matches_model_id_without_provider_prefix(self):
        assert _model_completion_matches("cl", "copilot", "claude-haiku-4.5")
        assert _model_completion_matches("hku", "copilot", "claude-haiku-4.5")
        assert not _model_completion_matches("zz", "copilot", "claude-haiku-4.5")


# ── ToolStatusWidget ─────────────────────────────────────────────────


class TestToolStatusWidget:
    def test_instantiate(self):
        w = ToolStatusWidget("bash", "ls -la")
        assert w.tool_name == "bash"
        assert w.args_str == "ls -la"

    def test_activity_progress_instantiates(self):
        progress = ActivityProgress()
        assert progress._running is False
        assert progress._offset == 0


class TestInfoBar:
    def test_update_info_records_agent_and_model(self):
        bar = InfoBar()
        bar.update_info(
            provider="copilot",
            model="claude-haiku-4.5",
            agent_id="DEF",
        )

        assert bar._agent_id == "DEF"
        assert bar._model == "claude-haiku-4.5"
        assert bar._provider == "copilot"

    def test_update_info_records_token_usage(self):
        bar = InfoBar()
        bar.update_info(
            provider="copilot",
            model="claude-haiku-4.5",
            tokens=1200,
            max_tokens=180000,
        )

        assert bar._tokens == 1200
        assert bar._max_tokens == 180000

    def test_context_badge_click_posts_message(self):
        from taui.tui.widgets.info_bar import ContextBadge

        badge = ContextBadge()
        posted: list[object] = []
        badge.post_message = posted.append  # type: ignore[method-assign]

        badge.on_click()

        assert isinstance(posted[0], InfoBar.ContextBadgeClicked)


class TestInfo2:
    async def test_show_context_tree_mounts_tree(self):
        from textual.widgets import Tree

        from taui.agent.types import Message
        from taui.llm_provider.types import ProviderToolCall
        from taui.tui.widgets.info2 import Info2, Info2Mode

        class Info2Harness(App[None]):
            def compose(self):
                yield Info2(id="info2")

        app = Info2Harness()
        long_user_content = "Explain the code without cutting off this long content."
        messages = [
            Message(
                role="system",
                content=(
                    "You are a helper.\n\n"
                    "# Available tools\n"
                    "- read: read files\n\n"
                    "# Guidelines\n"
                    "Be concise."
                ),
            ),
            Message(role="user", content=long_user_content),
            Message(
                role="assistant",
                content="I will inspect it.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_1",
                        name="read",
                        arguments={"path": "taui/tui/widgets/info2.py"},
                    )
                ],
            ),
            Message(
                role="tool",
                content="file contents",
                tool_call_id="call_1",
                name="read",
            ),
        ]

        async with app.run_test() as pilot:
            info2 = app.query_one("#info2", Info2)
            info2.show_context_tree(messages, 180000)
            await pilot.pause()

            tree = info2.query_one(Tree)
            assert info2.mode == Info2Mode.CONTEXT
            assert info2.is_active
            assert "Context" in str(tree.root.label)
            assert len(tree.root.children) == 3
            labels = [str(child.label) for child in tree.root.children]
            assert "system" in labels[0]
            assert "tool def" in labels[1]
            assert "user: " in labels[2]
            # Preview text from first 30 chars of long_user_content
            assert long_user_content[:30] in labels[2]
            assert "tokens" not in labels[2]
            assert "[" in labels[2] and "]" in labels[2]
            assert tree.root.children[2].label.spans
            assert all(not child.is_expanded for child in tree.root.children)
            tool_def_labels = [
                child.label.plain
                for group in tree.root.children[1].children
                for child in group.children
            ]
            assert "- read: read files" in tool_def_labels

            user = tree.root.children[2]
            user_labels = [
                child.label.plain
                for group in user.children
                for child in group.children
            ]
            assert long_user_content in user_labels
            assistant = next(
                child for child in user.children if "assistant" in str(child.label)
            )
            assert not assistant.is_expanded
            assert not any("role:" in str(child.label) for child in assistant.children)
            assert not any("tokens:" in str(child.label) for child in assistant.children)
            # tool_call: ... leaf lines were removed — tool messages already
            # appear as separate child nodes under the assistant turn.
            assert not any(
                "tool_call:" in str(child.label) for child in assistant.children
            )
            assert any("tool" in str(child.label) for child in assistant.children)

            info2.show_context_tree(messages, 180000)
            await pilot.pause()

            assert len(info2.query(Tree)) == 1
            assert info2.query_one(Tree).has_class("context-tree")

    async def test_show_approval_focuses_info2(self):
        from taui.tui.widgets.info2 import Info2, Info2Item, Info2Mode

        class Info2Harness(App[None]):
            def compose(self):
                yield Info2(id="info2")

        app = Info2Harness()

        async with app.run_test() as pilot:
            info2 = app.query_one("#info2", Info2)
            info2.show_approval("bash", "command=ls", "ls *")
            await pilot.pause()

            assert info2.mode == Info2Mode.APPROVAL
            assert app.focused is info2
            labels = [str(item.render()) for item in info2.query(Info2Item)]
            assert any("Allow all bash commands (project extension)" in lb for lb in labels)
            assert any("Allow all bash commands (global extension)" in lb for lb in labels)

    async def test_approval_can_select_project_tool_scope(self):
        from taui.tui.widgets.info2 import Info2

        class Info2Harness(App[None]):
            def compose(self):
                yield Info2(id="info2")

        app = Info2Harness()

        async with app.run_test() as pilot:
            info2 = app.query_one("#info2", Info2)
            info2.show_approval("bash", "command=ls", "ls *")
            waiter = asyncio.create_task(info2.wait_for_approval())
            await pilot.pause()

            info2.selected_index = 2
            info2.accept()
            result = await waiter

            assert result.approved is True
            assert result.pattern is None
            assert result.tool_scope == "project"


# ── Messages ─────────────────────────────────────────────────────────


class TestMessages:
    def test_tool_started(self):
        msg = ToolStarted("bash_1", "bash", "ls -la")
        assert msg.tool_key == "bash_1"
        assert msg.tool_name == "bash"
        assert msg.args_str == "ls -la"

    def test_tool_ended(self):
        msg = ToolEnded("bash_1", "bash", "output", False)
        assert msg.tool_key == "bash_1"
        assert not msg.is_error

    def test_tool_ended_error(self):
        msg = ToolEnded("bash_1", "bash", "error msg", True)
        assert msg.is_error

    def test_stream_text_delta(self):
        msg = StreamTextDelta("hello ")
        assert msg.text == "hello "


# ── ApprovalController notifications ─────────────────────────────────


class TestApprovalControllerNotifications:
    async def test_question_from_active_session_is_marked_active(self):
        from taui.tui.approval_controller import ApprovalController

        class FakeChatInput:
            disabled = False
            focused = False

            def focus(self) -> None:
                self.focused = True

        class FakePanel:
            _future = None

            async def wait_for_answers(self) -> list[str | None]:
                return [None]

        class FakeInfo2:
            hidden = False

            def show_questions(self, specs):
                return FakePanel()

            def hide(self) -> None:
                self.hidden = True

        class FakeApp:
            def __init__(self) -> None:
                self.chat_input = FakeChatInput()
                self.info2 = FakeInfo2()
                self.notifications: list[dict] = []
                self._sessions = SimpleNamespace(active=None)

            def query_one(self, selector, *_args):
                if selector == "#chat-input":
                    return self.chat_input
                if selector == "#info2":
                    return self.info2
                raise AssertionError(selector)

            def _smart_scroll(self) -> None:
                pass

            def _notify_user(self, _header, _message, **kwargs) -> None:
                self.notifications.append(kwargs)

        app = FakeApp()
        controller = ApprovalController(app)  # type: ignore[arg-type]
        app._sessions.active = SimpleNamespace(approval_ctrl=controller)

        answers = await controller.on_questions_batch([("Pick one", None)])

        assert answers == [None]
        assert app.notifications == [
            {"kind": "question", "from_active_session": True}
        ]

    async def test_question_from_inactive_session_is_marked_background(self):
        from taui.tui.approval_controller import ApprovalController

        class FakeChatInput:
            disabled = False

            def focus(self) -> None:
                pass

        class FakePanel:
            _future = None

            async def wait_for_answers(self) -> list[str | None]:
                return [None]

        class FakeInfo2:
            def show_questions(self, specs):
                return FakePanel()

            def hide(self) -> None:
                pass

        class FakeApp:
            def __init__(self) -> None:
                self.notifications: list[dict] = []
                self._sessions = SimpleNamespace(
                    active=SimpleNamespace(approval_ctrl=object())
                )

            def query_one(self, selector, *_args):
                if selector == "#chat-input":
                    return FakeChatInput()
                if selector == "#info2":
                    return FakeInfo2()
                raise AssertionError(selector)

            def _smart_scroll(self) -> None:
                pass

            def _notify_user(self, _header, _message, **kwargs) -> None:
                self.notifications.append(kwargs)

        app = FakeApp()
        controller = ApprovalController(app)  # type: ignore[arg-type]

        await controller.on_questions_batch([("Pick one", None)])

        assert app.notifications == [
            {"kind": "question", "from_active_session": False}
        ]


# ── FIFO tool tracking ──────────────────────────────────────────────


class TestToolFIFO:
    def test_fifo_ordering(self):
        """Verify FIFO key assignment and pop order."""
        app = TauiApp()

        # Simulate two concurrent bash tool calls
        app._tool_counter += 1
        key1 = f"bash_{app._tool_counter}"
        app._pending_tool_keys.setdefault("bash", []).append(key1)

        app._tool_counter += 1
        key2 = f"bash_{app._tool_counter}"
        app._pending_tool_keys.setdefault("bash", []).append(key2)

        assert app._pending_tool_keys["bash"] == ["bash_1", "bash_2"]

        # Pop first (FIFO)
        popped = app._pending_tool_keys["bash"].pop(0)
        assert popped == "bash_1"

        popped = app._pending_tool_keys["bash"].pop(0)
        assert popped == "bash_2"

    def test_fallback_on_empty_queue(self):
        """When FIFO queue is empty, fallback scan works."""
        app = TauiApp()
        mock_widget = MagicMock()
        app._active_tool_widgets["bash_5"] = mock_widget

        # No pending keys for bash
        keys = app._pending_tool_keys.get("bash", [])
        assert keys == []

        # Fallback finds the widget
        tool_key = next(
            (k for k in app._active_tool_widgets if k.startswith("bash")),
            "bash_unknown",
        )
        assert tool_key == "bash_5"


# ── StatusBar ────────────────────────────────────────────────────────


class TestStatusBar:
    def test_model_status_initial(self):
        ms = ModelStatus()
        assert ms._provider == ""
        assert ms._model == ""

    def test_model_status_set_info(self):
        ms = ModelStatus()
        ms.set_info("copilot", "claude-sonnet", extensions_mode=True)
        assert ms._provider == "copilot"
        assert ms._model == "claude-sonnet"
        assert ms._extensions_mode is True

    def test_context_status_initial(self):
        cs = ContextStatus()
        assert cs._tokens == 0


# ── Footer ───────────────────────────────────────────────────────────


class TestFooter:
    def test_idle_footer(self):
        f = CustomFooter(busy=False)
        text = f.render()
        assert "send" in text.plain
        assert "newline" in text.plain

    def test_busy_footer(self):
        f = CustomFooter(busy=True)
        text = f.render()
        assert "steer" in text.plain
        assert "queue" in text.plain
        assert "cancel" in text.plain

    def test_sidebar_shortcut_shown(self):
        f = CustomFooter(busy=False)
        text = f.render()
        assert "sidebar" in text.plain
        assert "context" in text.plain


# ── Sidebar ──────────────────────────────────────────────────────────


class TestSidebar:
    def test_instantiate(self, tmp_path):
        s = Sidebar(tmp_path)
        assert s._working_dir == tmp_path

    def test_default_cwd(self):
        s = Sidebar()
        assert s._working_dir == Path.cwd()


# ── TerminalOutput ───────────────────────────────────────────────────


class TestTerminalOutput:
    def test_instantiate(self):
        t = TerminalOutput("ls -la")
        assert t._command == "ls -la"
        assert t._buffer == ""


# ── ApprovalPrompt ───────────────────────────────────────────────────


class TestApprovalPrompt:
    def test_instantiate(self):
        p = ApprovalPrompt("bash", "cmd=ls")
        assert p.tool_name == "bash"
        assert p.args_summary == "cmd=ls"

    def test_responded_message(self):
        msg = ApprovalPrompt.Responded(approved=True)
        assert msg.approved is True
        msg2 = ApprovalPrompt.Responded(approved=False)
        assert msg2.approved is False


# ── QuestionsPanel ───────────────────────────────────────────────────


class TestQuestionsPanel:
    def test_instantiate_multi(self):
        specs = [
            QuestionSpec("What color?", ["red", "blue"]),
            QuestionSpec("Your name?"),
        ]
        panel = QuestionsPanel(specs)
        assert len(panel._specs) == 2
        assert panel._current == 0

    def test_instantiate_single(self):
        panel = QuestionsPanel([QuestionSpec("Pick one", ["a", "b"])])
        assert len(panel._specs) == 1

    def test_answers_initialized_to_none(self):
        specs = [QuestionSpec("Q1"), QuestionSpec("Q2")]
        panel = QuestionsPanel(specs)
        assert panel._answers == [None, None]

    def test_confirmed_message(self):
        msg = QuestionsPanel.Confirmed(["red", "Alice"])
        assert msg.answers == ["red", "Alice"]

    def test_question_spec_defaults(self):
        spec = QuestionSpec("What?")
        assert spec.question == "What?"
        assert spec.options is None

    def test_question_spec_with_options(self):
        spec = QuestionSpec("Pick", ["a", "b"])
        assert spec.options == ["a", "b"]

    def test_custom_answers_initialized_empty(self):
        specs = [QuestionSpec("Q1"), QuestionSpec("Q2")]
        panel = QuestionsPanel(specs)
        assert panel._custom_answers == ["", ""]

    def test_select_custom_answer_uses_typed_value(self):
        panel = QuestionsPanel([QuestionSpec("Pick", ["a", "b"])])
        panel._custom_answers[0] = "other"

        class Event:
            option_index = 2

        panel.on_option_list_option_selected(Event())  # type: ignore[arg-type]

        assert panel._answers == ["other"]

    def test_select_empty_custom_answer_is_none(self):
        panel = QuestionsPanel([QuestionSpec("Pick", ["a", "b"])])

        class Event:
            option_index = 2

        panel.on_option_list_option_selected(Event())  # type: ignore[arg-type]

        assert panel._answers == [None]

    def test_click_on_custom_row_focuses_instead_of_resolving(self):
        from taui.tui.widgets.questions_panel import QuestionOptionList

        panel = QuestionsPanel([QuestionSpec("Pick", ["a", "b"])])

        # Stand-in for the OptionList that hasn't entered typing mode.
        class FakeOL(QuestionOptionList):
            def __init__(self):
                pass

            def activate(self) -> None:  # type: ignore[override]
                self._custom_active = True

            def replace_option_prompt(self, *_a, **_kw):
                return None

        ol = FakeOL()
        ol._custom_active = False

        class Event:
            option_index = 2
            option_list = ol

            def stop(self):
                return None

        panel.on_option_list_option_selected(Event())  # type: ignore[arg-type]
        assert ol.is_custom_active
        assert panel._answers == [None]


# ── ContextBreakdownScreen ──────────────────────────────────────────


class TestContextBreakdownScreen:
    def test_instantiate(self):
        from taui.agent.loop import Message
        msgs = [
            Message(role="system", content="You are a helper."),
            Message(role="user", content="Hello"),
        ]
        s = ContextBreakdownScreen(msgs)
        assert s._messages == msgs


class TestGitDiffScreen:
    async def test_file_panel_toggles_diff_body(self):
        from taui.tui.screens.git_diff import _DiffFilePanel

        file = {
            "path": "hello.py",
            "old_path": "hello.py",
            "new_path": "hello.py",
            "status": "M",
            "old_text": "print('hello')\n",
            "new_text": "print('hello')\nprint('taui')\n",
        }
        panel = _DiffFilePanel(file, index=0)

        class PanelApp(App[None]):
            def compose(self):
                yield panel

        app = PanelApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert panel._body.display is False
            assert "▸" in panel._row_markup()

            await panel.toggle()
            await pilot.pause()

            assert panel._body.display is True
            assert panel._mounted_diff is True
            assert "▾" in panel._row_markup()

            await panel._header.on_click()
            await pilot.pause()

            assert panel._body.display is False
            assert "▸" in panel._row_markup()


# ── AgentResponse ────────────────────────────────────────────────────


class TestAgentResponse:
    def test_instantiate(self):
        r = AgentResponse()
        assert r._buffer == ""
        assert r._finalized is False


# ── ActivityProgress ─────────────────────────────────────────────────


class TestActivityProgress:
    def test_instantiate(self):
        progress = ActivityProgress()
        assert progress._running is False
        assert progress._offset == 0
        assert progress._direction == 1
        assert progress._active_style == "#3fb950"
        assert progress.render().plain == "━" * 40

    def test_advance_changes_rendered_bar(self):
        progress = ActivityProgress()
        progress._running = True
        before = progress.render()
        progress._advance_bounce()
        after = progress.render()

        assert before.plain == after.plain
        assert before.spans != after.spans
        assert progress._offset == 1

    def test_render_reverses_at_bar_edges(self):
        progress = ActivityProgress()
        progress._running = True
        progress._offset = 1000
        progress.render()
        assert progress._direction == -1

        progress._offset = -4
        progress.render()
        assert progress._direction == 1

    def test_active_style_updates_rendered_segment(self):
        progress = ActivityProgress()
        progress.set_active_style("#58a6ff")
        progress._running = True
        rendered = progress.render()

        assert progress._active_style == "#58a6ff"
        assert any(str(span.style) == "#58a6ff" for span in rendered.spans)


# ── Context-start banner update on agent switch ───────────────────────


class TestContextStartBanner:
    def test_banner_reflects_agent_system_prompt(self, tmp_path):
        """_build_context_banner_parts must reflect current _system_prompt and agent_id."""
        from taui.config import Config
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        class FakeLoop:
            agent_id = "DEF"
            _executor = ToolExecutor(registry=ToolRegistry(), policy=ToolPolicy())

        class FakeSession:
            _system_prompt = "Default agent prompt."
            _base_system_prompt = "Default agent prompt."
            _self_edit_prompt = ""
            _extensions_prompt = ""
            _registry = ToolRegistry()
            _loop = FakeLoop()
            self_edit_mode = False
            extensions_mode = False

        app = TauiApp(Config(working_dir=tmp_path))
        app._session = FakeSession()

        sp1, _tlabel1, _tbody1, _style1 = app._build_context_banner_parts()
        assert "Default agent prompt" in sp1

        # Simulate agent switch — update prompt and agent_id
        FakeSession._system_prompt = "You are PLN, a planning agent."
        FakeLoop.agent_id = "PLN"

        sp2, _tlabel2, _tbody2, style2 = app._build_context_banner_parts()
        assert "planning agent" in sp2
        assert sp1 != sp2, "System prompt did not change after agent switch"
        assert style2  # label style should be present

    def test_apply_profile_calls_notify_config_changed(self, tmp_path):
        """_apply_self_edit_profile must call _notify_config_changed."""
        from taui.config import Config
        from taui.cost import CostTracker
        from taui.self_edit.store import AgentProfile
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"
            system_prompt = ""
            max_turns = 50

        class FakeLoop:
            agent_id = "DEF"
            stream_id = "stream-1"
            _messages = []

        class FakeSession:
            config = FakeConfig()
            _provider = object()
            _registry = ToolRegistry()
            _executor = ToolExecutor(registry=_registry, policy=ToolPolicy())
            _stream = object()
            _loop = FakeLoop()
            _system_prompt = ""
            _base_system_prompt = ""
            provider_name = "copilot"
            extensions_mode = False
            self_edit_mode = False
            cost_tracker = CostTracker()
            _config_change_listeners: list = []
            _notified = False

            def _replace_loop(self, loop):
                self._loop = loop

            def add_config_change_listener(self, cb):
                self._config_change_listeners.append(cb)

            def _notify_config_changed(self):
                self._notified = True
                for cb in self._config_change_listeners:
                    try:
                        cb()
                    except Exception:
                        pass

        app = TauiApp(Config(working_dir=tmp_path))
        app._session = FakeSession()
        app._update_status = MagicMock()

        profile = AgentProfile(
            id="PLN",
            name="Planner",
            prompt="You are PLN, a planning agent.",
            provider="",
            model="",
            allowed_tools=["read", "glob", "grep"],
        )
        app._apply_self_edit_profile(profile)

        assert app._session._notified, (
            "_apply_self_edit_profile did not call _notify_config_changed"
        )
        assert app._session._system_prompt == "You are PLN, a planning agent."
        assert app._session._loop.agent_id == "PLN"
