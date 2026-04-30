"""Tests for taui.commands."""

import pytest

from taui.commands.registry import CommandContext, CommandRegistry, CommandResult


# ── Test command ────────────────────────────────────────────────────────────────


class FakeCommand:
    name = "ping"
    description = "Test command"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if ctx.args:
            return CommandResult.ok(f"pong {ctx.args[0]}")
        return CommandResult.ok("pong")


class FailingCommand:
    name = "boom"
    description = "Always fails"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        raise RuntimeError("kaboom")


# ── Registry ────────────────────────────────────────────────────────────────────


class TestCommandRegistry:
    def test_register_and_get(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        cmd = reg.get("ping")
        assert cmd is not None
        assert cmd.name == "ping"

    def test_duplicate_raises(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        with pytest.raises(ValueError):
            reg.register(FakeCommand())

    def test_alias(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        reg.alias("p", "ping")
        assert reg.get("p") is not None
        assert reg.get("p").name == "ping"

    def test_alias_unknown_raises(self):
        reg = CommandRegistry()
        with pytest.raises(ValueError):
            reg.alias("p", "nope")

    def test_names(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        assert "ping" in reg.names

    def test_help_text(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        text = reg.help_text()
        assert "/ping" in text
        assert "Test command" in text

    async def test_execute_known(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        result = await reg.execute("/ping")
        assert result.output == "pong"
        assert not result.error

    async def test_execute_with_args(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        result = await reg.execute("/ping hello")
        assert result.output == "pong hello"

    async def test_execute_unknown(self):
        reg = CommandRegistry()
        reg.register(FakeCommand())
        result = await reg.execute("/nope")
        assert result.error
        assert "Unknown command" in result.output

    async def test_execute_not_slash(self):
        reg = CommandRegistry()
        result = await reg.execute("hello")
        assert result.error

    async def test_execute_error_caught(self):
        reg = CommandRegistry()
        reg.register(FailingCommand())
        result = await reg.execute("/boom")
        assert result.error
        assert "kaboom" in result.output


# ── Builtins ──────────────────────────────────────────────────────────────────


class TestBuiltinCommands:
    async def test_help(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/help")
        assert not result.error
        assert "/help" in result.output
        assert "/cost" in result.output

    async def test_cost_no_tracker(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/cost")
        assert result.error

    async def test_cost_with_tracker(self):
        from taui.commands.builtins import register_builtins
        from taui.cost import CostTracker

        tracker = CostTracker()
        tracker.record(model="test", input_tokens=100, output_tokens=50)

        reg = CommandRegistry()
        register_builtins(reg, get_tracker=lambda: tracker)
        result = await reg.execute("/cost")
        assert not result.error
        assert "100" in result.output
        assert "50" in result.output

    async def test_extensions_toggle_on(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            extensions_mode = False
            async def toggle_extensions_mode(self):
                self.extensions_mode = not self.extensions_mode
                return self.extensions_mode

        session = FakeSession()
        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: session)
        result = await reg.execute("/i")
        assert not result.error
        assert "ON" in result.output

    async def test_extensions_toggle_off(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            extensions_mode = True
            async def toggle_extensions_mode(self):
                self.extensions_mode = not self.extensions_mode
                return self.extensions_mode

        session = FakeSession()
        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: session)
        result = await reg.execute("/i")
        assert not result.error
        assert "OFF" in result.output

    async def test_extensions_no_session(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/i")
        assert result.error
        assert "No session" in result.output

    async def test_extensions_in_help(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/help")
        assert "/i" in result.output

    def test_extensions_system_prompt(self):
        from taui.session import _EXTENSIONS_SYSTEM_PROMPT

        assert "register(tools, commands, hooks)" in _EXTENSIONS_SYSTEM_PROMPT
        assert ".taui/extensions/" in _EXTENSIONS_SYSTEM_PROMPT
        assert "ToolResult" in _EXTENSIONS_SYSTEM_PROMPT
        assert "CommandResult" in _EXTENSIONS_SYSTEM_PROMPT
        assert "hooks.prompt" in _EXTENSIONS_SYSTEM_PROMPT
        assert "hooks.turn_summary" in _EXTENSIONS_SYSTEM_PROMPT
        assert "hooks.before_send" in _EXTENSIONS_SYSTEM_PROMPT

    async def test_sessions_no_session(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/sessions")
        assert result.error
        assert "No session" in result.output

    async def test_sessions_list_empty(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            async def list_sessions(self):
                return []

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/sessions")
        assert not result.error
        assert "No previous" in result.output

    async def test_sessions_list(self):
        from taui.commands.builtins import register_builtins
        import time

        class FakeSession:
            async def list_sessions(self):
                return [
                    {"session_id": "abc123", "description": "Test session",
                     "mode": "normal", "message_count": 5,
                     "last_active": time.time() - 120}
                ]

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/sessions")
        assert not result.error
        assert "abc123" in result.output
        assert "Test session" in result.output

    async def test_sessions_resume(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            extensions_mode = False
            async def resume_session(self, sid):
                return sid == "abc123"

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/sessions abc123")
        assert not result.error
        assert "Resumed" in result.output

    async def test_sessions_resume_not_found(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            async def resume_session(self, sid):
                return False

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/sessions nope")
        assert result.error
        assert "not found" in result.output

    async def test_new_session(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            extensions_mode = False
            session_id = "old"
            async def new_session(self):
                self.session_id = "new123"

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/new")
        assert not result.error
        assert "New session" in result.output

    async def test_new_session_no_session(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/new")
        assert result.error
        assert "No session" in result.output

    async def test_reload_command(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            def reload_extensions(self):
                return ["my_ext"]

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/reload")
        assert not result.error
        assert "my_ext" in result.output
        assert "1" in result.output

    async def test_reload_no_extensions(self):
        from taui.commands.builtins import register_builtins

        class FakeSession:
            def reload_extensions(self):
                return []

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/reload")
        assert not result.error
        assert "No extensions" in result.output

    async def test_reload_no_session(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/reload")
        assert result.error

    async def test_reload_in_help(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/help")
        assert "/reload" in result.output


# ═══ Write guard ══════════════════════════════════════════════════════════════


class TestExtensionsWriteGuard:
    def test_guard_allows_taui_dir(self, tmp_path):
        from taui.session import Session
        from taui.config import Config

        config = Config(working_dir=tmp_path, provider="copilot", model="test")
        # Minimal session for testing guard
        session = Session.__new__(Session)
        session.config = config

        taui_path = tmp_path / ".taui" / "extensions" / "test.py"
        taui_path.parent.mkdir(parents=True)
        result = session._extensions_guard(taui_path)
        assert result is None  # None means allowed

    def test_guard_rejects_outside(self, tmp_path):
        from taui.session import Session
        from taui.config import Config

        config = Config(working_dir=tmp_path, provider="copilot", model="test")
        session = Session.__new__(Session)
        session.config = config

        bad_path = tmp_path / "taui" / "cli.py"
        result = session._extensions_guard(bad_path)
        assert result is not None
        assert result.error
        assert "restricted" in result.content.lower()

    async def test_write_tool_with_guard(self, tmp_path):
        from taui.tools.builtins.files import WriteTool
        from taui.tools.base import ToolResult

        tool = WriteTool()
        tool.working_dir = tmp_path

        # Set a guard that rejects everything
        tool._path_guard = lambda p: ToolResult.fail("blocked")
        result = await tool.execute({"path": "test.txt", "content": "hi"})
        assert result.error
        assert "blocked" in result.content

    async def test_write_tool_without_guard(self, tmp_path):
        from taui.tools.builtins.files import WriteTool

        tool = WriteTool()
        tool.working_dir = tmp_path
        result = await tool.execute({"path": "test.txt", "content": "hi"})
        assert not result.error
        assert (tmp_path / "test.txt").read_text() == "hi"

    async def test_edit_tool_with_guard(self, tmp_path):
        from taui.tools.builtins.edit import EditTool
        from taui.tools.base import ToolResult

        # Create a file first
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        tool = EditTool()
        tool.working_dir = tmp_path
        tool._path_guard = lambda p: ToolResult.fail("blocked")
        result = await tool.execute({
            "path": "test.txt",
            "edits": [{"old_text": "hello", "new_text": "hi"}],
        })
        assert result.error
        assert "blocked" in result.content
