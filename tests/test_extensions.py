"""Tests for the extension system — discovery, loading, and lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from taui.extensions import Extension, ExtensionRegistry
from taui.extensions.builtins import BUILTIN_EXTENSION_NAMES
from taui.tools.registry import ToolRegistry
from taui.commands.registry import CommandRegistry


# ═══ Extension dataclass ══════════════════════════════════════════════════════


class TestExtension:
    def test_defaults(self):
        ext = Extension(name="test", path=Path("test.py"), scope="project")
        assert ext.enabled
        assert not ext.loaded
        assert ext.error is None


# ═══ ExtensionRegistry ════════════════════════════════════════════════════════


def _make_extension(
    base: Path, name: str, code: str, *, subdir: str = ".taui/extensions"
) -> Path:
    """Create an extension .py file."""
    ext_dir = base / subdir
    ext_dir.mkdir(parents=True, exist_ok=True)
    ext_file = ext_dir / f"{name}.py"
    ext_file.write_text(code, encoding="utf-8")
    return ext_file


class TestExtensionDiscovery:
    def test_discover_empty(self, tmp_path: Path):
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_discover_includes_builtins_when_requested(self, tmp_path: Path):
        reg = ExtensionRegistry(tmp_path, include_builtins=True)
        reg.discover()

        assert reg.names == sorted(BUILTIN_EXTENSION_NAMES)
        for name in BUILTIN_EXTENSION_NAMES:
            ext = reg.get(name)
            assert ext is not None
            assert ext.scope == "builtin"
            assert ext.loaded
            assert ext.path is None

    def test_discover_keeps_builtin_names_reserved(self, tmp_path: Path):
        _make_extension(tmp_path, "mcp", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path, include_builtins=True)
        reg.discover()

        ext = reg.get("mcp")
        assert ext is not None
        assert ext.scope == "builtin"
        assert ext.path is None

    def test_discover_project_extension(self, tmp_path: Path):
        _make_extension(tmp_path, "my_ext", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert "my_ext" in reg.names
        ext = reg.get("my_ext")
        assert ext.scope == "project"
        assert not ext.loaded

    def test_discover_multiple(self, tmp_path: Path):
        _make_extension(tmp_path, "alpha", "def register(tools, commands): pass")
        _make_extension(tmp_path, "beta", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert sorted(reg.names) == ["alpha", "beta"]

    def test_discover_ignores_underscore_files(self, tmp_path: Path):
        _make_extension(tmp_path, "_internal", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_discover_ignores_non_py_files(self, tmp_path: Path):
        ext_dir = tmp_path / ".taui" / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "readme.md").write_text("not an extension")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_discover_ignores_directories(self, tmp_path: Path):
        ext_dir = tmp_path / ".taui" / "extensions" / "subdir"
        ext_dir.mkdir(parents=True)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_get_missing(self, tmp_path: Path):
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        assert reg.get("nonexistent") is None

    def test_list_all(self, tmp_path: Path):
        _make_extension(tmp_path, "alpha", "def register(tools, commands): pass")
        _make_extension(tmp_path, "beta", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        all_exts = reg.list_all()
        assert len(all_exts) == 2
        assert [e.name for e in all_exts] == ["alpha", "beta"]


# ═══ ExtensionRegistry loading ════════════════════════════════════════════════


class TestExtensionLoading:
    def test_load_simple_extension(self, tmp_path: Path):
        _make_extension(
            tmp_path,
            "hello",
            "def register(tools, commands): pass",
        )
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        loaded = reg.load_all()
        assert loaded == ["hello"]
        assert reg.get("hello").loaded

    def test_load_extension_registers_tool(self, tmp_path: Path):
        code = '''
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult

@dataclass
class PingTool:
    name: str = "ping"
    description: str = "Returns pong"
    category: ToolCategory = ToolCategory.SEARCH
    guidelines: str = ""
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object", "properties": {}
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("pong")

def register(tools, commands):
    tools.register(PingTool())
'''
        _make_extension(tmp_path, "ping_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        tools = ToolRegistry()
        loaded = reg.load_all(tools=tools)
        assert loaded == ["ping_ext"]
        assert "ping" in tools

    def test_load_extension_registers_command(self, tmp_path: Path):
        code = '''
from dataclasses import dataclass
from taui.commands.registry import CommandContext, CommandResult

@dataclass(slots=True)
class PingCommand:
    name: str = "ping"
    description: str = "Returns pong"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult.ok("pong")

def register(tools, commands):
    commands.register(PingCommand())
'''
        _make_extension(tmp_path, "ping_cmd", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        commands = CommandRegistry()
        loaded = reg.load_all(commands=commands)
        assert loaded == ["ping_cmd"]
        assert commands.get("ping") is not None

    def test_load_broken_extension(self, tmp_path: Path):
        _make_extension(tmp_path, "broken", "raise RuntimeError('oops')")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        loaded = reg.load_all()
        assert loaded == []
        ext = reg.get("broken")
        assert not ext.loaded
        assert ext.error is not None

    def test_load_missing_register(self, tmp_path: Path):
        _make_extension(tmp_path, "no_register", "x = 1")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        loaded = reg.load_all()
        assert loaded == []
        ext = reg.get("no_register")
        assert not ext.loaded
        assert "register()" in ext.error

    def test_load_disabled_extension(self, tmp_path: Path):
        _make_extension(tmp_path, "disabled", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.get("disabled").enabled = False
        loaded = reg.load_all()
        assert loaded == []
        assert not reg.get("disabled").loaded

    def test_loaded_extensions(self, tmp_path: Path):
        _make_extension(tmp_path, "ext1", "def register(tools, commands): pass")
        _make_extension(tmp_path, "ext2", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.load_all()
        loaded = reg.loaded_extensions()
        assert len(loaded) == 2

    def test_load_idempotent(self, tmp_path: Path):
        """Loading the same extension twice doesn't re-execute."""
        counter_file = tmp_path / "counter"
        counter_file.write_text("0")
        code = f'''
def register(tools, commands):
    with open("{counter_file}", "r+") as f:
        n = int(f.read().strip())
        f.seek(0)
        f.write(str(n + 1))
'''
        _make_extension(tmp_path, "counted", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.load_all()
        reg.load_all()  # Second call should be no-op
        assert counter_file.read_text().strip() == "1"

    def test_load_extension_with_hooks(self, tmp_path: Path):
        """Extension with hooks parameter works."""
        from taui.hooks import HookRegistry

        code = '''
def register(tools, commands, hooks):
    hooks.banner(lambda session: "hello from ext")
'''
        _make_extension(tmp_path, "hook_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        hooks = HookRegistry()
        loaded = reg.load_all(hooks=hooks)
        assert loaded == ["hook_ext"]
        assert hooks.has("banner")
        assert hooks.count("banner") == 1

    def test_load_legacy_extension_without_hooks(self, tmp_path: Path):
        """Extension without hooks parameter still loads fine."""
        from taui.hooks import HookRegistry

        code = 'def register(tools, commands): pass'
        _make_extension(tmp_path, "legacy", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        hooks = HookRegistry()
        loaded = reg.load_all(hooks=hooks)
        assert loaded == ["legacy"]
        assert reg.get("legacy").loaded

    def test_load_new_style_ctx_extension(self, tmp_path: Path):
        """New-style register(ctx) extension loads and receives context."""
        from taui.hooks import HookRegistry

        code = '''
def register(ctx):
    ctx.hooks.banner(lambda session: "ctx-banner")
'''
        _make_extension(tmp_path, "ctx_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        hooks = HookRegistry()
        tools = ToolRegistry()
        loaded = reg.load_all(tools=tools, hooks=hooks)
        assert loaded == ["ctx_ext"]
        assert reg.get("ctx_ext").loaded
        assert hooks.has("banner")

    def test_load_new_style_ctx_registers_tool(self, tmp_path: Path):
        """New-style register(ctx) can register tools via ctx.tools."""
        code = '''
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult

@dataclass
class CtxTool:
    name: str = "ctx_tool"
    description: str = "tool via ctx"
    category: ToolCategory = ToolCategory.SEARCH
    guidelines: str = ""
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("ok")

def register(ctx):
    ctx.tools.register(CtxTool())
'''
        _make_extension(tmp_path, "ctx_tool_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()

        tools = ToolRegistry()
        loaded = reg.load_all(tools=tools)
        assert loaded == ["ctx_tool_ext"]
        assert "ctx_tool" in tools

    def test_load_new_style_ctx_skill_path(self, tmp_path: Path):
        """New-style register(ctx) can contribute skill paths."""
        skill_dir = tmp_path / ".taui" / "extensions" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "my-skill.md").write_text("# My Skill\nDo things.", encoding="utf-8")

        code = 'def register(ctx):\n    ctx.skills.add_path("skills/my-skill.md")\n'
        _make_extension(tmp_path, "skill_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.load_all()

        ext = reg.get("skill_ext")
        assert ext.loaded
        assert len(ext.skill_paths) == 1
        assert ext.skill_paths[0].name == "my-skill.md"

    def test_load_new_style_ctx_skill_path_missing_file(self, tmp_path: Path):
        """Nonexistent skill path is collected but loading is deferred to SkillRegistry."""
        code = 'def register(ctx):\n    ctx.skills.add_path("skills/ghost.md")\n'
        _make_extension(tmp_path, "ghost_ext", code)
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.load_all()

        ext = reg.get("ghost_ext")
        assert ext.loaded
        assert len(ext.skill_paths) == 1  # path is recorded; SkillRegistry warns if missing


# ═══ ExtensionsCommand ════════════════════════════════════════════════════════


class TestExtensionsCommand:
    async def test_extensions_command_empty(self):
        from taui.commands.builtins import ExtensionsCommand
        from taui.commands.registry import CommandContext

        cmd = ExtensionsCommand()
        reg = ExtensionRegistry(Path("/nonexistent"))
        reg.discover()
        cmd._get_extensions = lambda: reg
        result = await cmd.execute(CommandContext(raw_input="/extensions"))
        assert not result.error
        assert "No extensions" in result.output

    async def test_extensions_command_with_extensions(self, tmp_path: Path):
        from taui.commands.builtins import ExtensionsCommand
        from taui.commands.registry import CommandContext

        _make_extension(tmp_path, "myext", "def register(tools, commands): pass")
        reg = ExtensionRegistry(tmp_path)
        reg.discover()
        reg.load_all()

        cmd = ExtensionsCommand()
        cmd._get_extensions = lambda: reg
        result = await cmd.execute(CommandContext(raw_input="/extensions"))
        assert not result.error
        assert "myext" in result.output
        assert "loaded" in result.output
