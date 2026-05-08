from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Collapsible, Select, Static

from taui.config import Config
from taui.self_edit import SelfEditController, SelfEditSession, SelfEditStore
from taui.self_edit.controller import Selection
from taui.self_edit.panel import SelfEditPanel
from taui.self_edit.scaffolding import (
    NewExtensionRequest,
    NewToolRequest,
    extension_template,
    find_tool_source,
    infer_tool_category,
    slug_from_prompt,
    tool_extension_template,
)
from taui.self_edit.status_bar import SelfEditStatusBar
from taui.self_edit.store import AgentProfile, ExtensionSource
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from taui.tui.app import TauiApp
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.info_bar import InfoBar


@dataclass(slots=True)
class AnalyzeWorkspaceTool:
    name: str = "analyze_workspace"
    description: str = "Inspect the current project."
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("ok")


class _FakeLoop:
    def __init__(self) -> None:
        self._messages: list = []
        self._system_prompt = ""
        self.stream_id = "agents/fake"
        self.run_calls: list[str] = []

    async def run(self, text: str):
        self.run_calls.append(text)

        @dataclass
        class _R:
            text: str
        return _R(text=f"specialist saw: {text}")


class _FakeSession:
    def __init__(self, working_dir) -> None:
        self.config = Config(working_dir=working_dir)
        self._registry = ToolRegistry()
        register_builtins(self._registry)
        self._registry.register(AnalyzeWorkspaceTool())
        self._builtin_tool_names = set(self._registry.names)
        self._executor = ToolExecutor(registry=self._registry, policy=ToolPolicy())
        self._ext_registry = None
        self.reload_count = 0
        self._loop = _FakeLoop()
        self._provider = None
        self._stream = None
        self.session_id = "fake"
        self.replay_items = []
        self.last_resume_error = ""
        self.new_session_count = 0
        self.resumed: list[str] = []

    def reload_extensions(self):
        self.reload_count += 1
        return []

    def _replace_loop(self, loop) -> None:
        self._loop = loop

    async def new_session(self) -> None:
        self.new_session_count += 1
        self.session_id = f"fake-new-{self.new_session_count}"
        self._loop = _FakeLoop()
        self._loop.stream_id = f"agents/{self.session_id}"

    async def resume_session(self, session_id: str) -> bool:
        self.resumed.append(session_id)
        self.session_id = session_id
        self._loop = _FakeLoop()
        return True

    async def send(self, message: str):
        raise AssertionError("self-edit inventory must not call the LLM")


class _ControllerApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.wired = 0
        self.status = 0
        self.exited = False

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-area"):
            with VerticalScroll(id="chat-log"):
                pass
            yield Info2(id="info2")
            yield ChatInput(id="chat-input")
            yield InfoBar()

    def _wire_callbacks(self) -> None:
        self.wired += 1

    def _update_status(self) -> None:
        self.status += 1

    async def action_exit_self_edit(self) -> None:
        self.exited = True


def _make_controller(tmp_path):
    app = _ControllerApp()
    session = _FakeSession(tmp_path)
    state = SelfEditSession()
    controller = SelfEditController(
        app=app,
        session=session,
        config=session.config,
        state=state,
        store=SelfEditStore(tmp_path),
    )
    return app, session, state, controller


# ── Store / scaffolding tests (unchanged) ──────────────────────────────


def test_self_edit_scope_roundtrip(tmp_path):
    store = SelfEditStore(tmp_path)
    assert store.load_default_scope() == "project"
    store.save_default_scope("global")
    assert store.load_default_scope() == "global"


def test_agents_include_defaults_and_save_prompt_file(tmp_path):
    store = SelfEditStore(tmp_path)
    agents = store.load_agents()
    assert "BLD" in agents
    assert agents["BLD"].prompt_path is not None
    assert agents["BLD"].prompt_path.exists()

    custom = AgentProfile(
        id="ABC",
        name="Custom",
        prompt="p",
        provider="copilot",
        model="m",
        allowed_tools=["read"],
    )
    store.save_agent(custom, "project")

    loaded = store.load_agents()
    assert loaded["ABC"].name == "Custom"
    assert loaded["ABC"].prompt == "p"
    assert loaded["ABC"].prompt_path is not None
    assert loaded["ABC"].prompt_path.read_text(encoding="utf-8") == "p"


def test_inline_agent_prompt_migrates_to_markdown_file(tmp_path):
    base = tmp_path / ".taui" / "self_edit"
    base.mkdir(parents=True)
    agents_file = base / "agents.json"
    agents_file.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "ABC",
                        "name": "Old",
                        "prompt": "legacy prompt",
                        "provider": "",
                        "model": "",
                        "allowed_tools": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = SelfEditStore(tmp_path).load_agents()

    assert loaded["ABC"].prompt == "legacy prompt"
    assert loaded["ABC"].prompt_path is not None
    assert loaded["ABC"].prompt_path.exists()
    rewritten = json.loads(agents_file.read_text(encoding="utf-8"))
    assert "prompt_path" in rewritten["profiles"][0]
    assert "prompt" not in rewritten["profiles"][0]


def test_find_tool_source_prefers_tool_filename(tmp_path):
    path = tmp_path / "tool_custom.py"
    path.write_text("def register(tools, commands, hooks): pass")
    assert find_tool_source("custom", [path]) == path


def test_find_tool_source_by_declared_name(tmp_path):
    path = tmp_path / "everything.py"
    path.write_text('name: str = "custom"')
    assert find_tool_source("custom", [path]) == path


def test_prompt_helpers_construct_tool_metadata():
    assert slug_from_prompt("Search tests for broken fixtures", "fallback") == (
        "search_tests_broken_fixtures"
    )
    assert infer_tool_category("Find symbols and scan source files") == "search"


def test_tool_template_keeps_construction_prompt():
    source = tool_extension_template(
        NewToolRequest(
            name="scan_tests",
            description="Scan tests for missing coverage.",
            category="search",
            prompt="Scan tests for missing coverage.",
        )
    )

    assert "class ScanTestsTool" in source
    assert "ToolCategory.SEARCH" in source
    assert "construction_prompt" in source
    assert "Scan tests for missing coverage." in source


def test_extension_template_keeps_construction_prompt():
    source = extension_template(
        NewExtensionRequest(
            name="review_hooks",
            prompt="Add hooks that annotate review responses.",
        )
    )

    assert "CONSTRUCTION_PROMPT" in source
    assert "Add hooks that annotate review responses." in source


def test_extension_source_model():
    ext = ExtensionSource(
        name="mcp",
        path=None,
        scope="builtin",
        description="MCP server manager and invocation tool.",
        loaded=True,
    )

    assert ext.name == "mcp"
    assert ext.loaded is True


# ── v2 controller tests ────────────────────────────────────────────────


async def test_controller_help_lists_verbs(tmp_path):
    _, _, _, controller = _make_controller(tmp_path)
    output = await controller.handle("help")
    assert "self-edit verbs" in output
    assert "applicable" in output


async def test_controller_show_with_typed_form(tmp_path):
    _, _, _, controller = _make_controller(tmp_path)
    output = await controller.handle("show agent BLD")
    assert "agent BLD" in output


async def test_controller_show_requires_selection_or_typed(tmp_path):
    _, _, _, controller = _make_controller(tmp_path)
    output = await controller.handle("show")
    assert "select a row first" in output


async def test_controller_show_uses_panel_selection(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    state.selection = Selection(kind="agent", name="BLD")
    output = await controller.handle("show")
    assert "agent BLD" in output


async def test_controller_scope_persists(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    out = await controller.handle("scope global")
    assert "global" in out
    assert state.scope == "global"
    assert SelfEditStore(tmp_path).load_default_scope() == "global"


async def test_controller_rm_requires_yes_confirm(tmp_path):
    _, session, state, controller = _make_controller(tmp_path)
    # Create a custom tool extension to delete.
    ext_dir = tmp_path / ".taui" / "extensions"
    ext_dir.mkdir(parents=True)
    target = ext_dir / "tool_demo.py"
    target.write_text(
        'name: str = "demo"\ndef register(tools, commands, hooks): pass\n',
        encoding="utf-8",
    )
    # Pretend it's not built-in.
    session._builtin_tool_names.discard("demo")
    # Register a fake tool entry so the controller's lookup finds the path.

    @dataclass(slots=True)
    class DemoTool:
        name: str = "demo"
        description: str = "demo"
        category: ToolCategory = ToolCategory.AGENT
        schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

        async def execute(self, arguments):  # pragma: no cover
            return ToolResult.ok("")

    session._registry.register(DemoTool())

    state.selection = Selection(kind="tool", name="demo")
    prompt = await controller.handle("rm")
    assert "type 'yes'" in prompt
    # Anything other than 'yes' cancels.
    cancelled = await controller.handle("nope")
    assert cancelled == "cancelled"
    assert target.exists()

    # Now confirm.
    await controller.handle("rm")
    deleted = await controller.handle("yes")
    assert "deleted" in deleted
    assert not target.exists()


async def test_controller_rm_refuses_builtin(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    # Pick any built-in tool name.
    builtin = next(iter(controller._session._builtin_tool_names))
    state.selection = Selection(kind="tool", name=builtin)
    output = await controller.handle("rm")
    assert "built-in" in output or "can't delete" in output


async def test_controller_add_swaps_playbook(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    state.selection = Selection(kind="tool", name="")
    output = await controller.handle("add tool")
    assert "playbook" in output
    assert state.active_playbook == "add_tool"


async def test_controller_edit_builtin_tool_redirects(tmp_path):
    _, session, state, controller = _make_controller(tmp_path)
    builtin = next(iter(session._builtin_tool_names))
    state.selection = Selection(kind="tool", name=builtin)
    output = await controller.handle("edit")
    assert "built-in" in output
    assert state.active_playbook is None


async def test_controller_cancel_clears_playbook(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    state.active_playbook = "add_tool"
    output = await controller.handle("cancel")
    assert "cleared" in output
    assert state.active_playbook is None


async def test_controller_unknown_verb_returns_help(tmp_path):
    _, _, _, controller = _make_controller(tmp_path)
    output = await controller.handle("frobnicate")
    assert "unknown verb" in output
    assert "self-edit verbs" in output


async def test_controller_compose_system_prompt_includes_base(tmp_path):
    _, _, state, controller = _make_controller(tmp_path)
    prompt = controller.specialist_system_prompt()
    assert "self-edit assistant" in prompt
    state.active_playbook = "add_tool"
    prompt2 = controller.specialist_system_prompt()
    assert "self-edit assistant" in prompt2
    assert "Active playbook: add tool" in prompt2


async def test_controller_reload_refreshes_panel(tmp_path):
    app, session, state, controller = _make_controller(tmp_path)
    output = await controller.handle("reload")
    assert output == "reloaded extensions"
    assert session.reload_count == 1
    assert app.wired == 1
    assert app.status == 1


# ── App-level tests ────────────────────────────────────────────────────


class _ModeApp(TauiApp):
    def _wire_callbacks(self) -> None:
        return None

    def _update_status(self) -> None:
        return None


async def test_app_enters_self_edit_mounts_panel_and_status(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test():
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        assert app._self_edit is not None
        assert app.query_one(SelfEditStatusBar).is_mounted
        assert str(app.query_one(SelfEditStatusBar).render()) == "selection: -"
        assert app.query_one(SelfEditPanel).is_mounted
        # Specialist loop was installed.
        assert app._self_edit.specialist_loop is app._session._loop
        assert app._self_edit.previous_session_id == "fake"
        assert app._session.session_id == "fake-new-1"
        assert app._session._loop.stream_id == "agents/fake-new-1"


async def test_app_exits_self_edit_restores_loop_and_reloads(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test():
        session = _FakeSession(tmp_path)
        app._session = session
        await app.action_enter_self_edit()
        assert session.session_id == "fake-new-1"
        await app.action_exit_self_edit()
        assert app._self_edit is None
        assert session.resumed == ["fake"]
        assert session.reload_count == 1


async def test_app_new_in_self_edit_clears_specialist_history(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test():
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        # Pretend the specialist accumulated some messages.
        app._self_edit.specialist_loop._messages = ["a", "b"]
        app._self_edit_controller.reset_specialist_history()
        assert app._self_edit.specialist_loop._messages == []


async def test_self_edit_panel_sections_are_accordion(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test() as pilot:
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        panel = app.query_one(SelfEditPanel)
        agent = panel.query_one("#se-section-agent", Collapsible)
        tool = panel.query_one("#se-section-tool", Collapsible)

        assert agent.collapsed is False
        tool.collapsed = False
        await pilot.pause()

        assert tool.collapsed is False
        assert agent.collapsed is True


async def test_self_edit_selection_is_shown_in_panel_footer(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test() as pilot:
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        panel = app.query_one(SelfEditPanel)

        panel.post_message(SelfEditPanel.RowSelected("tool", "bash"))
        await pilot.pause()

        assert panel.selected_kind == "tool"
        assert panel.selected_name == "bash"
        assert str(app.query_one(SelfEditStatusBar).render()) == "selection: tool bash"
        assert "playbook" not in str(panel.query_one("#self-edit-panel-footer", Static).render())


async def test_self_edit_scope_dropdown_persists(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test() as pilot:
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        panel = app.query_one(SelfEditPanel)
        scope_select = panel.query_one("#self-edit-scope-select", Select)

        scope_select.value = "global"
        await pilot.pause()

        assert app._self_edit.scope == "global"
        assert panel.scope == "global"
        assert SelfEditStore(tmp_path).load_default_scope() == "global"
