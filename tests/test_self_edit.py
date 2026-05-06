from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll

from taui.config import Config
from taui.self_edit import SelfEditController, SelfEditSession, SelfEditStore
from taui.self_edit.scaffolding import (
    NewExtensionRequest,
    NewToolRequest,
    infer_tool_category,
    slug_from_prompt,
)
from taui.self_edit.scaffolding import (
    extension_template,
    find_tool_source,
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
from taui.tui.widgets.completion_dropdown import CompletionDropdown
from taui.tui.widgets.info_bar import InfoBar


@dataclass(slots=True)
class AnalyzeWorkspaceTool:
    name: str = "analyze_workspace"
    description: str = "Inspect the current project."
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("ok")


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

    def reload_extensions(self):
        self.reload_count += 1
        return []

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
            yield CompletionDropdown(id="completion-dropdown")
            yield ChatInput(id="chat-input")
            yield InfoBar()

    def _wire_callbacks(self) -> None:
        self.wired += 1

    def _update_status(self) -> None:
        self.status += 1

    async def action_exit_self_edit(self) -> None:
        self.exited = True


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


async def test_controller_lists_agents(tmp_path):
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

    output = await controller.handle("agents")

    assert "BLD" in output
    assert "PLN" in output


async def test_controller_summary_lists_local_inventory(tmp_path):
    app = _ControllerApp()
    session = _FakeSession(tmp_path)
    store = SelfEditStore(tmp_path)
    store.save_agent(
        AgentProfile(
            id="REV",
            name="Review",
            prompt="Review code.",
            provider="",
            model="",
            allowed_tools=[],
        ),
        "project",
    )
    skill_dir = tmp_path / ".taui" / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Debug\n", encoding="utf-8")
    ext_dir = tmp_path / ".taui" / "extensions"
    ext_dir.mkdir(parents=True)
    (ext_dir / "sample.py").write_text("def register(tools, commands, hooks): pass")
    state = SelfEditSession()
    controller = SelfEditController(
        app=app,
        session=session,
        config=session.config,
        state=state,
        store=store,
    )

    output = controller.summary()

    assert "### Agents (" in output
    assert "| `REV` | Review |" in output
    assert "### Tools (" in output
    assert "analyze_workspace" in output
    assert "### Skills (" in output
    assert "| `debug` | project |" in output
    assert "### Extensions (" in output
    assert "| `sample` | project |" in output


async def test_controller_new_agent_flow_creates_file_and_json(tmp_path):
    app = _ControllerApp()
    session = _FakeSession(tmp_path)
    state = SelfEditSession()
    store = SelfEditStore(tmp_path)
    controller = SelfEditController(
        app=app,
        session=session,
        config=session.config,
        state=state,
        store=store,
    )

    assert "enter prompt" in await controller.handle("new agent")
    output = await controller.handle("Review diffs and suggest focused fixes.")

    assert "created agent" in output
    agents = store.load_agents()
    created = [agent for agent in agents.values() if agent.name.startswith("Review")]
    assert created
    assert created[0].prompt_path is not None
    assert created[0].prompt_path.exists()


async def test_controller_reload_rewires_app(tmp_path):
    app = _ControllerApp()
    session = _FakeSession(tmp_path)
    controller = SelfEditController(
        app=app,
        session=session,
        config=session.config,
        state=SelfEditSession(),
        store=SelfEditStore(tmp_path),
    )

    output = await controller.handle("reload")

    assert output == "reloaded extensions"
    assert session.reload_count == 1
    assert app.wired == 1
    assert app.status == 1


class _ModeApp(TauiApp):
    def _wire_callbacks(self) -> None:
        return None

    def _update_status(self) -> None:
        return None


async def test_app_enters_self_edit_and_status_bar_is_mounted(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test():
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        assert app._self_edit is not None
        assert app.query_one(SelfEditStatusBar).is_mounted
        assert app._self_edit_controller is not None
        text = app._self_edit_controller.summary()
        assert "### Agents (" in text
        assert "### Tools (" in text
        assert "### Skills (" in text
        assert "### Extensions (" in text


async def test_app_exits_self_edit_and_reloads(tmp_path):
    app = _ModeApp(Config(working_dir=tmp_path))
    async with app.run_test():
        app._session = _FakeSession(tmp_path)
        await app.action_enter_self_edit()
        await app.action_exit_self_edit()
        assert app._self_edit is None
        assert app._session.reload_count == 1
