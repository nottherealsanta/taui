"""Tests for taui.commands."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "hello.py"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


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
        assert "/context" in result.output

    async def test_context_command_opens_tree(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/context")

        assert not result.error
        assert result.metadata["action"] == "open_context_tree"

    async def test_diff_command_opens_diff_view(self, tmp_path):
        from taui.commands.builtins import register_builtins

        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('hello')\nprint('taui')\n")

        class FakeSession:
            working_dir = tmp_path

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/diff")

        assert not result.error
        assert result.metadata["action"] == "open_diff_view"
        assert result.metadata["files"][0]["path"] == "hello.py"
        assert "print('taui')" in result.metadata["files"][0]["new_text"]

    async def test_diff_command_supports_staged_changes(self, tmp_path):
        from taui.commands.builtins import register_builtins

        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('hello')\nprint('staged')\n")
        subprocess.run(
            ["git", "add", "hello.py"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        class FakeSession:
            working_dir = tmp_path

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/diff --staged")

        assert not result.error
        assert result.metadata["title"] == "Staged Diff"
        assert "print('staged')" in result.metadata["files"][0]["new_text"]

    async def test_diff_command_supports_ref_changes(self, tmp_path):
        from taui.commands.builtins import register_builtins

        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('hello')\nprint('ref')\n")

        class FakeSession:
            working_dir = tmp_path

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/diff --ref HEAD")

        assert not result.error
        assert result.metadata["title"] == "Diff Against HEAD"
        assert "print('ref')" in result.metadata["files"][0]["new_text"]

    async def test_review_command_sends_read_only_prompt(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/review --staged --security")

        assert not result.error
        assert result.metadata["action"] == "send_prompt"
        assert result.metadata["tool_names"] == ["read", "grep", "glob", "git", "peek"]
        assert "security review" in result.metadata["prompt"]
        assert "staged changes" in result.metadata["prompt"]

    async def test_commit_command_sends_confirmation_prompt(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/commit fix widget state")

        assert not result.error
        assert result.metadata["action"] == "send_prompt"
        assert "ask me to confirm" in result.metadata["prompt"]
        assert "fix widget state" in result.metadata["prompt"]

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

    async def test_self_edit_command(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        # /i opens the self-edit modal
        result = await reg.execute("/i")
        assert not result.error
        assert result.metadata["action"] == "self_edit_open"
        assert result.metadata["message"] == ""

        # /i list dumps the inventory as text — the message carries the subcommand
        result = await reg.execute("/i list agents")
        assert not result.error
        assert result.metadata["action"] == "self_edit_open"
        assert result.metadata["message"] == "list agents"

    def test_no_argument_commands_are_marked_for_completion_submit(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)

        # /new, /i, /model, and /agents all accept args for inline completion.
        assert getattr(reg.get("new"), "accepts_args") is True
        assert getattr(reg.get("i"), "accepts_args") is True
        assert getattr(reg.get("model"), "accepts_args") is True
        assert getattr(reg.get("agents"), "accepts_args") is True

    async def test_model_list_has_no_reasoning_icon(self, monkeypatch):
        from taui.commands.builtins import register_builtins

        class FakeConfig:
            provider = "copilot"
            model = "claude-haiku-4.5"

        class FakeLoop:
            _model = "claude-haiku-4.5"

        class FakeSession:
            config = FakeConfig()
            _loop = FakeLoop()

        monkeypatch.setattr(
            "taui.llm_provider.models.list_models",
            lambda provider, force_refresh=False: [
                {
                    "id": "claude-haiku-4.5",
                    "context": 200000,
                    "reasoning": True,
                }
            ],
        )

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/model list")

        assert not result.error
        assert "🧠" not in result.output
        assert "reasoning" in result.output

    async def test_model_accepts_current_provider_model_value(self):
        from taui.commands.builtins import register_builtins

        class FakeConfig:
            provider = "copilot"
            model = "old"

        class FakeLoop:
            _model = "old"

        class FakeSession:
            session_id = "session-2"
            config = FakeConfig()
            _loop = FakeLoop()
            new_session_called = False

            async def new_session(self):
                self.new_session_called = True

        session = FakeSession()
        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: session)
        result = await reg.execute("/model copilot/claude-haiku-4.5")

        assert not result.error
        assert session.config.provider == "copilot"
        assert session.config.model == "claude-haiku-4.5"
        assert session._loop._model == "claude-haiku-4.5"
        assert session.new_session_called is False
        assert result.metadata["action"] == "model_changed"
        assert result.metadata["model"] == "claude-haiku-4.5"

    async def test_variant_accepts_explicit_none_when_model_supports_it(self, monkeypatch):
        from taui.commands.builtins import register_builtins

        session = SimpleNamespace(
            config=SimpleNamespace(provider="codex", model="gpt-5.3-codex", model_variant=""),
            _loop=SimpleNamespace(_model_variant=""),
        )
        monkeypatch.setattr(
            "taui.llm_provider.models.get_model_variants",
            lambda provider, model: ["none", "low", "medium", "high"],
        )

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: session)
        result = await reg.execute("/variant none")

        assert not result.error
        assert session.config.model_variant == "none"
        assert session._loop._model_variant == "none"
        assert result.metadata["variant"] == "none"

    async def test_variant_clear_alias_still_clears(self, monkeypatch):
        from taui.commands.builtins import register_builtins

        session = SimpleNamespace(
            config=SimpleNamespace(
                provider="codex", model="gpt-5.3-codex", model_variant="high"
            ),
            _loop=SimpleNamespace(_model_variant="high"),
        )
        monkeypatch.setattr(
            "taui.llm_provider.models.get_model_variants",
            lambda provider, model: ["none", "low", "medium", "high"],
        )

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: session)
        result = await reg.execute("/variant clear")

        assert not result.error
        assert session.config.model_variant == ""
        assert session._loop._model_variant == ""
        assert result.metadata["variant"] == ""

    async def test_model_rejects_other_provider_model_value(self):
        from taui.commands.builtins import register_builtins

        class FakeConfig:
            provider = "copilot"
            model = "old"

        class FakeLoop:
            _model = "old"

        class FakeSession:
            config = FakeConfig()
            _loop = FakeLoop()

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/model codex/gpt-5.3-codex")

        assert result.error
        assert "Use /provider codex" in result.output

    async def test_agents_list_marks_active_profile(self, tmp_path):
        from taui.commands.builtins import register_builtins
        from taui.self_edit import AgentProfile

        class FakeLoop:
            agent_id = "PLN"

        class FakeSession:
            _loop = FakeLoop()

        class FakeStore:
            def load_agents(self):
                return {
                    "BLD": AgentProfile("BLD", "Build", "build", "", "", [], tmp_path / "BLD.md"),
                    "PLN": AgentProfile("PLN", "Plan", "plan", "copilot", "m1", [], None),
                }

        reg = CommandRegistry()
        register_builtins(
            reg,
            get_session=lambda: FakeSession(),
            get_store=lambda: FakeStore(),
        )
        result = await reg.execute("/agents")

        assert not result.error
        assert result.metadata.get("action") == "open_agent_picker"

        # /agents list still works
        result = await reg.execute("/agents list")
        assert not result.error
        assert "BLD  Build" in result.output
        assert "PLN  Plan" in result.output
        assert "copilot/m1" in result.output
        assert "PLN" in result.output
        assert "◀" in result.output
        assert "Activate: /agents <ID>" in result.output

    async def test_agents_activate_profile(self, tmp_path):
        from taui.commands.builtins import register_builtins
        from taui.self_edit import AgentProfile

        class FakeLoop:
            agent_id = "BLD"

        class FakeSession:
            _loop = FakeLoop()

        profile = AgentProfile("PLN", "Plan", "plan", "", "", [], tmp_path / "PLN.md")
        applied = []

        class FakeStore:
            def load_agents(self):
                return {"PLN": profile}

        reg = CommandRegistry()
        register_builtins(
            reg,
            get_session=lambda: FakeSession(),
            get_store=lambda: FakeStore(),
            get_apply_profile=applied.append,
        )
        result = await reg.execute("/agents pln")

        assert not result.error
        assert result.output == ""
        assert result.metadata["action"] == "agent_activated"
        assert result.metadata["agent_id"] == "PLN"
        assert applied == [profile]

    async def test_agents_unknown_id_lists_available_ids(self):
        from taui.commands.builtins import register_builtins
        from taui.self_edit import AgentProfile

        class FakeLoop:
            agent_id = "BLD"

        class FakeSession:
            _loop = FakeLoop()

        class FakeStore:
            def load_agents(self):
                return {
                    "BLD": AgentProfile("BLD", "Build", "build", "", "", [], None),
                    "PLN": AgentProfile("PLN", "Plan", "plan", "", "", [], None),
                }

        reg = CommandRegistry()
        register_builtins(
            reg,
            get_session=lambda: FakeSession(),
            get_store=lambda: FakeStore(),
            get_apply_profile=lambda profile: None,
        )
        result = await reg.execute("/agents tst")

        assert result.error
        assert "Unknown agent: TST" in result.output
        assert "Available: BLD, PLN" in result.output

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
        result = await reg.execute("/ext-mode")
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
        result = await reg.execute("/ext-mode")
        assert not result.error
        assert "OFF" in result.output

    async def test_extensions_no_session(self):
        from taui.commands.builtins import register_builtins
        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/ext-mode")
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
        import time

        from taui.commands.builtins import register_builtins

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
        assert result.metadata["action"] == "session_picker"
        assert result.metadata["sessions"][0]["session_id"] == "abc123"

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

    async def test_debug_questions(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/debug questions")
        assert not result.error
        assert result.metadata["action"] == "debug_questions"

    async def test_debug_usage(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        # /debug requires an arg — empty invocation is a no-op (not an error).
        result = await reg.execute("/debug")
        assert not result.error
        assert result.output == ""

        # An unrecognized arg still reports usage.
        result = await reg.execute("/debug nope")
        assert result.error
        assert "/debug questions" in result.output

    async def test_copy_copies_context_json(self, monkeypatch):
        from taui.commands.builtins import register_builtins

        copied: dict[str, bytes | list[str]] = {}

        def fake_run(cmd, *, input, check, timeout):
            copied["cmd"] = cmd
            copied["input"] = input
            assert check is True
            assert timeout == 5

        class FakeLoop:
            _messages = [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hello"},
            ]

            def _build_llm_messages(self):
                return self._messages

        class FakeSession:
            session_id = "session-1"
            provider_name = "copilot"
            model_name = "mock-model"
            _loop = FakeLoop()

        monkeypatch.setattr(subprocess, "run", fake_run)

        reg = CommandRegistry()
        register_builtins(reg, get_session=lambda: FakeSession())
        result = await reg.execute("/copy")

        assert not result.error
        assert copied["cmd"] == ["pbcopy"]
        payload = json.loads(copied["input"].decode())
        assert payload == {
            "session_id": "session-1",
            "provider": "copilot",
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hello"},
            ],
        }
        assert "2 messages" in result.output

    async def test_copy_no_session(self):
        from taui.commands.builtins import register_builtins

        reg = CommandRegistry()
        register_builtins(reg)
        result = await reg.execute("/copy")
        assert result.error
        assert "No session" in result.output


# ═══ Write guard ══════════════════════════════════════════════════════════════


class TestExtensionsWriteGuard:
    def test_guard_allows_taui_dir(self, tmp_path):
        from taui.config import Config
        from taui.session import Session

        config = Config(working_dir=tmp_path, provider="copilot", model="test")
        # Minimal session for testing guard
        session = Session.__new__(Session)
        session.config = config

        taui_path = tmp_path / ".taui" / "extensions" / "test.py"
        taui_path.parent.mkdir(parents=True)
        result = session._extensions_guard(taui_path)
        assert result is None  # None means allowed

    def test_guard_rejects_outside(self, tmp_path):
        from taui.config import Config
        from taui.session import Session

        config = Config(working_dir=tmp_path, provider="copilot", model="test")
        session = Session.__new__(Session)
        session.config = config

        bad_path = tmp_path / "taui" / "cli.py"
        result = session._extensions_guard(bad_path)
        assert result is not None
        assert result.error
        assert "restricted" in result.content.lower()

    async def test_write_tool_with_guard(self, tmp_path):
        from taui.tools.base import ToolResult
        from taui.tools.builtins.files import WriteTool

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
        from taui.tools.base import ToolResult
        from taui.tools.builtins.edit import EditTool

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
