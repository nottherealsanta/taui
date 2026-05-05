from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import TabbedContent

from taui.config import Config
from taui.tools.builtins import register_builtins
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.registry import ToolRegistry
from taui.tui.widgets.self_edit import (
    AgentProfile,
    ExtensionSource,
    SelfEditStore,
    _builtin_extension_summary,
    _extension_option_label,
    _find_tool_source,
)
from taui.tui.widgets.self_edit import SelfEditView


@dataclass(slots=True)
class AnalyzeWorkspaceTool:
    name: str = "analyze_workspace"
    description: str = (
        "Inspect the current project structure and return a concise summary of likely "
        "entry points, tests, and extension hooks."
    )
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "description": "Optional area to emphasize in the summary.",
            },
        },
        "required": [],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(f"focus: {arguments.get('focus', 'project')}")


class _SnapshotSession:
    def __init__(self, working_dir) -> None:
        self._registry = ToolRegistry()
        register_builtins(self._registry)
        self._registry.register(AnalyzeWorkspaceTool())
        self._builtin_tool_names = set(self._registry.names)
        self._builtin_tool_names.remove("analyze_workspace")

        ext_dir = working_dir / ".taui" / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "tool_analyze_workspace.py").write_text(
            """from taui.tools.base import ToolResult


async def execute(arguments):
    return ToolResult.ok("workspace analyzed")
""",
            encoding="utf-8",
        )


class _SelfEditToolsApp(App[None]):
    CSS = """
    Screen {
        background: #0f0d06;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._session = _SnapshotSession(config.working_dir)

    def compose(self) -> ComposeResult:
        yield SelfEditView(config=self._config, session=self._session)

    def on_mount(self) -> None:
        self.query_one(TabbedContent).active = "tools"


class _SelfEditCloseApp(_SelfEditToolsApp):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.closed = False

    async def action_close_self_edit(self) -> None:
        self.closed = True


def test_self_edit_scope_roundtrip(tmp_path):
    store = SelfEditStore(tmp_path)
    assert store.load_default_scope() == "project"
    store.save_default_scope("global")
    assert store.load_default_scope() == "global"


def test_agents_include_defaults_and_save(tmp_path):
    store = SelfEditStore(tmp_path)
    agents = store.load_agents()
    assert "BLD" in agents
    assert "PLN" in agents

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


def test_find_tool_source_prefers_tool_filename(tmp_path):
    path = tmp_path / "tool_custom.py"
    path.write_text("def register(tools, commands, hooks): pass")
    assert _find_tool_source("custom", [path]) == path


def test_find_tool_source_by_declared_name(tmp_path):
    path = tmp_path / "everything.py"
    path.write_text('name: str = "custom"')
    assert _find_tool_source("custom", [path]) == path


def test_builtin_extension_label_and_summary():
    ext = ExtensionSource(
        name="mcp",
        path=None,
        scope="builtin",
        description="MCP server manager and invocation tool.",
        loaded=True,
    )

    assert _extension_option_label(ext) == "mcp [builtin] - loaded"
    summary = _builtin_extension_summary(ext)
    assert "MCP server manager" in summary
    assert "read-only" in summary


def test_self_edit_tools_visual_snapshot(tmp_path, snap_compare):
    app = _SelfEditToolsApp(Config(working_dir=tmp_path))
    assert snap_compare(app, terminal_size=(110, 34))


async def test_self_edit_exit_button_calls_close_action(tmp_path):
    app = _SelfEditCloseApp(Config(working_dir=tmp_path))
    async with app.run_test() as pilot:
        await pilot.click("#self-exit")
        assert app.closed is True
