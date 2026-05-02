"""Tests for taui.cli.app — CliApp rendering, streaming, and markdown."""

import asyncio
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from taui.agent.loop import AgentLoop, RunResult, TurnResult
from taui.cli.app import CliApp
from taui.config import Config
from taui.cost import CostTracker
from taui.hooks import HookRegistry
from taui.llm_provider.types import ProviderTurnResult, Usage
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry


# ── Mock provider ─────────────────────────────────────────────────────


class MockProvider:
    """Scripted responses for testing."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_count = 0

    async def create_turn(self, messages, model, *, tools=None, **kw):
        text = (
            self._responses[self._call_count]
            if self._call_count < len(self._responses)
            else "done"
        )
        self._call_count += 1
        return ProviderTurnResult(
            response_id=None,
            text=text,
            tool_calls=[],
            usage=Usage(input_tokens=100, output_tokens=50),
        )


# ── Fixtures ──────────────────────────────────────────────────────────


async def _make_session(tmp_path, responses=None):
    """Build a real Session with a mock provider."""
    from taui.session import Session

    config = Config(working_dir=tmp_path)
    provider = MockProvider(responses or ["Hello, world!"])

    registry = ToolRegistry()
    register_builtins(registry)
    executor = ToolExecutor(registry=registry, policy=ToolPolicy())

    store = Store(tmp_path)
    await store.connect()
    stream = StreamClient(store)

    loop = AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt=config.system_prompt,
        model=config.model,
    )

    return Session(
        config=config,
        provider=provider,
        registry=registry,
        executor=executor,
        store=store,
        stream=stream,
        loop=loop,
    )


def _capture_console() -> tuple[Console, StringIO]:
    """Create a Console that writes to a StringIO buffer."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    return console, buf


# ── Tests: _print and _print_md ──────────────────────────────────────


class TestPrintOutput:
    async def test_print_plain(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._print("hello world")
        output = buf.getvalue()
        assert "hello world" in output
        await session.close()

    async def test_print_styled(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._print("error!", style="red")
        output = buf.getvalue()
        assert "error!" in output
        await session.close()

    async def test_print_markdown(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._print_md("# Hello\n\nThis is **bold** text.")
        output = buf.getvalue()
        assert "Hello" in output
        assert "bold" in output
        await session.close()

    async def test_print_markdown_code_block(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._print_md("```python\nprint('hello')\n```")
        output = buf.getvalue()
        assert "print" in output
        await session.close()


# ── Tests: streaming via _on_text_delta + _end_stream ────────────────


class TestStreaming:
    async def test_text_delta_accumulates(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        app._on_text_delta("Hello")
        assert app._streaming is True
        assert app._stream_buffer == "Hello"

        app._on_text_delta(", world!")
        assert app._stream_buffer == "Hello, world!"
        await session.close()

    async def test_end_stream_renders_markdown(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        # Simulate streaming
        app._streaming = True
        app._stream_buffer = "# Response\n\nHere is **bold** text."

        app._end_stream()

        assert app._streaming is False
        assert app._stream_buffer == ""
        output = buf.getvalue()
        assert "Response" in output
        assert "bold" in output
        await session.close()

    async def test_end_stream_empty_buffer(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._streaming = True
        app._stream_buffer = ""
        app._end_stream()

        assert app._streaming is False
        # No output when buffer is empty
        assert buf.getvalue().strip() == ""
        await session.close()


# ── Tests: Live display ──────────────────────────────────────────────


class TestLiveDisplay:
    def _render(self, renderable) -> str:
        """Render a Rich renderable to plain text."""
        buf = StringIO()
        c = Console(file=buf, force_terminal=False, width=80)
        c.print(renderable)
        return buf.getvalue()

    async def test_build_live_renderable_no_stream(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        renderable = app._build_live_renderable()
        text = self._render(renderable)
        assert "thinking" in text
        await session.close()

    async def test_build_live_renderable_with_stream(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        app._streaming = True
        app._stream_buffer = "partial response text"
        renderable = app._build_live_renderable()
        text = self._render(renderable)
        assert "partial response text" in text
        assert "thinking" in text
        await session.close()

    async def test_build_live_renderable_streams_markdown(
        self, tmp_path
    ):
        """Verify markdown is rendered during streaming, not raw text."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._streaming = True
        app._stream_buffer = "# Title\n\nSome **bold** text."
        renderable = app._build_live_renderable()
        text = self._render(renderable)
        # Markdown heading and bold should be present (rendered)
        assert "Title" in text
        assert "bold" in text
        await session.close()

    async def test_build_live_renderable_truncates_long_stream(
        self, tmp_path
    ):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        app._streaming = True
        app._stream_buffer = "\n".join(
            f"line {i}" for i in range(20)
        )
        renderable = app._build_live_renderable()
        text = self._render(renderable)
        # Full content is rendered as markdown now
        assert "line 0" in text
        assert "line 19" in text
        await session.close()

    async def test_start_stop_live(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._start_live()
        assert app._live is not None

        app._stop_live()
        assert app._live is None
        await session.close()


# ── Tests: tool call / result display ────────────────────────────────


class TestToolCallbacks:
    async def test_on_tool_call(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._on_tool_call("id1", "read_file", {"path": "foo.py"})
        output = buf.getvalue()
        assert "read_file" in output
        assert "▸" in output
        await session.close()

    async def test_on_tool_result_success_verbose(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console
        session.config.verbose_tools = True

        await app._on_tool_result(
            "id1", "read_file", "line1\nline2\nline3", False
        )
        output = buf.getvalue()
        assert "line1" in output
        assert "line2" in output
        await session.close()

    async def test_on_tool_result_success_quiet(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console
        session.config.verbose_tools = False

        await app._on_tool_result(
            "id1", "read_file", "line1\nline2\nline3", False
        )
        output = buf.getvalue()
        assert "✓" in output
        assert "read_file" in output
        assert "3 lines" in output
        # Actual content should NOT appear
        assert "line1" not in output
        await session.close()

    async def test_on_tool_result_error(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._on_tool_result(
            "id1", "write_file", "Permission denied", True
        )
        output = buf.getvalue()
        assert "✗" in output
        assert "Permission denied" in output
        await session.close()

    async def test_on_tool_result_truncates(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console
        session.config.verbose_tools = True

        content = "\n".join(f"line {i}" for i in range(20))
        await app._on_tool_result("id1", "bash", content, False)
        output = buf.getvalue()
        # Shows first 3 non-empty lines then "... (N more lines)"
        assert "line 0" in output
        assert "line 1" in output
        assert "line 2" in output
        assert "more lines" in output
        await session.close()


# ── Tests: _send full flow ───────────────────────────────────────────


class TestSendFlow:
    async def test_send_displays_response(self, tmp_path):
        session = await _make_session(tmp_path, ["This is the answer."])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._send("what is 2+2?")
        output = buf.getvalue()

        # Should show the response
        assert "This is the answer." in output
        # Should show turn summary
        assert "1 turn" in output
        await session.close()

    async def test_send_shows_markdown_response(self, tmp_path):
        md = "# Answer\n\nThe result is **4**."
        session = await _make_session(tmp_path, [md])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._send("what is 2+2?")
        output = buf.getvalue()

        assert "Answer" in output
        assert "4" in output
        await session.close()

    async def test_send_shows_token_usage(self, tmp_path):
        session = await _make_session(tmp_path, ["hi"])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._send("hello")
        output = buf.getvalue()

        # MockProvider returns 100 input, 50 output
        assert "100→50" in output
        await session.close()


# ── Tests: @file resolution ──────────────────────────────────────────


class TestAtFileResolution:
    async def test_resolve_at_file(self, tmp_path):
        (tmp_path / "readme.md").write_text("# Hello")
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        result = app._resolve_at_files("check @readme.md please")
        assert "# Hello" in result
        assert "```readme.md" in result
        await session.close()

    async def test_resolve_at_file_missing(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        result = app._resolve_at_files("check @nonexistent.py")
        assert result == "check @nonexistent.py"
        await session.close()

    async def test_resolve_at_file_path_traversal(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        result = app._resolve_at_files("@../../etc/passwd")
        assert "```" not in result
        await session.close()


# ── Tests: dispatch routing ──────────────────────────────────────────


class TestDispatch:
    async def test_slash_command(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._dispatch("/help")
        output = buf.getvalue()
        assert "help" in output.lower()
        await session.close()

    async def test_quit_command(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        await app._dispatch("/quit")
        assert app._should_exit is True
        await session.close()

    async def test_shell_command(self, tmp_path):
        session = await _make_session(tmp_path, ["got it"])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._dispatch("!echo hello")
        output = buf.getvalue()
        assert "hello" in output
        await session.close()

    async def test_normal_message(self, tmp_path):
        session = await _make_session(tmp_path, ["response"])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._dispatch("tell me something")
        output = buf.getvalue()
        assert "response" in output
        await session.close()


# ── Tests: status line ────────────────────────────────────────────────


class TestStatusLine:
    async def test_basic_status(self, tmp_path):
        session = await _make_session(tmp_path)
        app = CliApp(session)

        status = app._status_line()
        assert "copilot/" in status
        await session.close()

    async def test_status_after_send(self, tmp_path):
        session = await _make_session(tmp_path, ["hi"])
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        await app._send("hello")
        status = app._status_line()
        # After send, should have token count or cost
        assert "copilot/" in status
        await session.close()


# ── Tests: inline steering input ──────────────────────────────────────


class TestSteeringInput:
    async def test_live_renderable_shows_input_prompt(self, tmp_path):
        """Live renderable always shows '> ' input prompt."""
        session = await _make_session(tmp_path)
        app = CliApp(session)

        renderable = app._build_live_renderable()
        buf = StringIO()
        Console(file=buf, force_terminal=False, width=80).print(renderable)
        text = buf.getvalue()
        assert "> " in text
        await session.close()

    async def test_live_renderable_shows_typed_text(self, tmp_path):
        """Input buffer appears in the Live renderable."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        app._input_buffer = "fix the tests"

        renderable = app._build_live_renderable()
        buf = StringIO()
        Console(file=buf, force_terminal=False, width=80).print(renderable)
        text = buf.getvalue()
        assert "fix the tests" in text
        await session.close()

    async def test_on_stdin_readable_enter_steers(self, tmp_path):
        """Enter sends input buffer to steering queue."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        # Simulate: type "focus on X" then Enter
        app._input_buffer = "focus on X"
        app._start_live()
        import os
        r, w = os.pipe()
        old_stdin = __import__("sys").stdin
        try:
            __import__("sys").stdin = open(r)
            os.write(w, b"\r")
            os.close(w)
            app._on_stdin_readable()
        finally:
            __import__("sys").stdin.close()
            __import__("sys").stdin = old_stdin
            app._stop_live()
            await session.close()

        assert app._input_buffer == ""
        assert "focus on X" in session._loop._steering_queue
        assert ("s", "focus on X") in app._pending_indicators

    async def test_on_stdin_readable_backspace(self, tmp_path):
        """Backspace removes last character from input buffer."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        app._start_live()

        app._input_buffer = "hello"
        import os
        r, w = os.pipe()
        old_stdin = __import__("sys").stdin
        try:
            __import__("sys").stdin = open(r)
            os.write(w, b"\x7f")
            os.close(w)
            app._on_stdin_readable()
        finally:
            __import__("sys").stdin.close()
            __import__("sys").stdin = old_stdin
            app._stop_live()
            await session.close()

        assert app._input_buffer == "hell"

    async def test_on_stdin_readable_printable(self, tmp_path):
        """Printable characters are appended to input buffer."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        app._start_live()

        import os
        r, w = os.pipe()
        old_stdin = __import__("sys").stdin
        try:
            __import__("sys").stdin = open(r)
            os.write(w, b"abc")
            os.close(w)
            app._on_stdin_readable()
        finally:
            __import__("sys").stdin.close()
            __import__("sys").stdin = old_stdin
            app._stop_live()
            await session.close()

        assert app._input_buffer == "abc"

    async def test_on_stdin_readable_ctrl_u_clears(self, tmp_path):
        """Ctrl-U clears the input buffer."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        app._start_live()

        app._input_buffer = "some text"
        import os
        r, w = os.pipe()
        old_stdin = __import__("sys").stdin
        try:
            __import__("sys").stdin = open(r)
            os.write(w, b"\x15")
            os.close(w)
            app._on_stdin_readable()
        finally:
            __import__("sys").stdin.close()
            __import__("sys").stdin = old_stdin
            app._stop_live()
            await session.close()

        assert app._input_buffer == ""

    async def test_dispatch_steers_during_agent_work(self, tmp_path):
        """Dispatch routes input to steering when agent is working."""
        session = await _make_session(tmp_path)
        app = CliApp(session)
        console, buf = _capture_console()
        app._console = console

        app._agent_working = True
        await app._dispatch("refocus on tests")
        assert "refocus on tests" in session._loop._steering_queue
        assert ("s", "refocus on tests") in app._pending_indicators
        await session.close()

    async def test_dispatch_queues_during_agent_work(self, tmp_path):
        """Dispatch routes q-prefixed input to queue when agent is working."""
        session = await _make_session(tmp_path)
        app = CliApp(session)

        app._agent_working = True
        await app._dispatch("q fix the tests next")
        assert "fix the tests next" in app._queued
        assert ("q", "fix the tests next") in app._pending_indicators
        assert not session._loop._steering_queue
        await session.close()

    async def test_dispatch_steers_with_s_prefix(self, tmp_path):
        """Dispatch routes s-prefixed input to steering."""
        session = await _make_session(tmp_path)
        app = CliApp(session)

        app._agent_working = True
        await app._dispatch("s focus on error handling")
        assert "focus on error handling" in session._loop._steering_queue
        assert ("s", "focus on error handling") in app._pending_indicators
        await session.close()
