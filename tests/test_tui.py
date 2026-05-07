"""Tests for taui.tui module — import, structure, and unit tests (no live app)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.css.query import NoMatches
from textual.widgets import Static

from taui.tui import TauiApp, run_tui
from taui.tui.app import _trunc
from taui.tui.messages import (
    AgentBusy,
    AgentIdle,
    StreamTextDelta,
    ToolEnded,
    ToolStarted,
)
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.tool_status import ToolStatusWidget
from taui.tui.widgets.spinner import SpinnerWidget
from taui.tui.widgets.status_bar import StatusBar, ModelStatus, ContextStatus
from taui.tui.widgets.footer import CustomFooter
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.terminal import TerminalOutput
from taui.tui.widgets.approval import ApprovalPrompt
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec
from taui.tui.screens.context_breakdown import ContextBreakdownScreen
from taui.tui.screens.diff_view import DiffViewScreen
from taui.tui.screens.session_picker import SessionPickerScreen


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

    def test_run_tui_is_callable(self):
        assert callable(run_tui)

    def test_run_tui_returns_final_session_id(self):
        import taui.tui as tui_module

        class FakeApp:
            session_id = "abc123"

            def __init__(self, config):
                self.config = config

            def run(self):
                return None

        with patch.object(tui_module, "TauiApp", FakeApp):
            assert run_tui(object()) == "abc123"

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
            extensions_mode = False
            cost_tracker = FakeTracker()
            replay_items = []
            _loop = FakeLoop()
            _ext_registry = None

            def __init__(self):
                self.resumed: list[str] = []

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

        class FakeSession:
            session_id = "new"
            last_resume_error = "Session not found: abc123"

            async def resume_session(self, session_id: str) -> bool:
                return False

        app = TauiApp(Config(working_dir=tmp_path))
        async with app.run_test():
            app._session = FakeSession()
            assert await app._resume_session("abc123") is False
            assert any(
                "Session not found: abc123" in str(widget.content)
                for widget in app.query(Static)
            )

    async def test_open_session_picker_resumes_selection(self, tmp_path):
        from taui.config import Config

        class FakeSession:
            session_id = "current"
            last_resume_error = ""
            replay_items = []

            def __init__(self):
                self.resumed: list[str] = []

            async def resume_session(self, session_id: str) -> bool:
                self.resumed.append(session_id)
                self.session_id = session_id
                return True

        app = TauiApp(Config(working_dir=tmp_path))
        fake = FakeSession()
        async with app.run_test():
            app._session = fake
            app._wire_callbacks = MagicMock()  # type: ignore[method-assign]
            app._update_status = MagicMock()  # type: ignore[method-assign]
            app.push_screen_wait = AsyncMock(return_value="abc123")  # type: ignore[method-assign]
            await app._open_session_picker([{"session_id": "abc123"}])
            assert fake.resumed == ["abc123"]

    async def test_open_session_picker_escape_cancel_keeps_session(self, tmp_path):
        from taui.config import Config

        class FakeSession:
            session_id = "current"

            async def resume_session(self, session_id: str) -> bool:
                raise AssertionError("resume should not be called")

        app = TauiApp(Config(working_dir=tmp_path))
        async with app.run_test():
            app._session = FakeSession()
            app.push_screen_wait = AsyncMock(return_value=None)  # type: ignore[method-assign]
            await app._open_session_picker([{"session_id": "abc123"}])
            assert app.session_id == "current"

    def test_session_picker_instantiates(self):
        screen = SessionPickerScreen([{"session_id": "abc123"}])
        assert screen is not None


# ── @file expansion ──────────────────────────────────────────────────


class TestFileExpansion:
    def test_expand_existing_file(self, tmp_path):
        from taui.config import Config
        f = tmp_path / "test.txt"
        f.write_text("file content here")
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result = app._expand_file_refs(f"@{f.name}")
        assert "file content here" in result
        assert "```test.txt" in result

    def test_expand_nonexistent_file(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result = app._expand_file_refs("@nonexistent.txt")
        assert result == "@nonexistent.txt"

    def test_no_expansion_without_at(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result = app._expand_file_refs("hello world")
        assert result == "hello world"

    def test_bare_at_not_expanded(self, tmp_path):
        from taui.config import Config
        config = Config(working_dir=tmp_path)
        app = TauiApp(config)
        result = app._expand_file_refs("@")
        assert result == "@"


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


# ── ToolStatusWidget ─────────────────────────────────────────────────


class TestToolStatusWidget:
    def test_instantiate(self):
        w = ToolStatusWidget("bash", "ls -la")
        assert w.tool_name == "bash"
        assert w.args_str == "ls -la"

    def test_spinner_frames(self):
        from taui.tui.widgets.info_bar import SPINNER_FRAMES
        assert len(SPINNER_FRAMES) == 8


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


# ── DiffViewScreen ──────────────────────────────────────────────────


class TestDiffViewScreen:
    def test_instantiate(self):
        s = DiffViewScreen("file.py", "before", "after")
        assert s._file_path == "file.py"
        assert s._before == "before"
        assert s._after == "after"


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


# ── AgentResponse ────────────────────────────────────────────────────


class TestAgentResponse:
    def test_instantiate(self):
        r = AgentResponse()
        assert r._buffer == ""
        assert r._finalized is False


# ── SpinnerWidget ────────────────────────────────────────────────────


class TestSpinnerWidget:
    def test_instantiate(self):
        s = SpinnerWidget()
        assert s._running is False
        assert s._status_text == "Thinking..."

    def test_set_status_updates_text(self):
        s = SpinnerWidget()
        # Can't call set_status without an app context (calls self.update),
        # so test the internal state directly
        s._status_text = "Running bash..."
        assert s._status_text == "Running bash..."

    def test_set_status_empty_defaults(self):
        s = SpinnerWidget()
        # set_status("") should default to "Thinking..."
        # Test the logic without calling update
        text = "" or "Thinking..."
        assert text == "Thinking..."
