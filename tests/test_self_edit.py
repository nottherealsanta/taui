from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from taui.agent.loop import AgentLoop
from taui.agent.types import Message
from taui.config import Config
from taui.self_edit.factory import (
    build_scoped_tool_registry,
    build_self_edit_executor,
    build_self_edit_system_prompt,
    load_self_edit_system_prompt,
)
from taui.self_edit.scoping import PathAllowlist, wrap_tool_with_allowlist
from taui.self_edit.store import (
    AgentProfile,
    ExtensionSource,
    SelfEditStore,
    ToolConfig,
)
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.executor import (
    Completed,
    NeedsApproval,
    PolicyDecision,
    ToolExecutor,
    ToolPolicy,
)
from taui.tools.registry import ToolRegistry

# ── Store tests ────────────────────────────────────────────────────────


def test_self_edit_scope_roundtrip(tmp_path):
    store = SelfEditStore(tmp_path)
    assert store.load_default_scope() == "global"
    store.save_default_scope("global")
    assert store.load_default_scope() == "global"


def test_agents_include_defaults_and_save_prompt_file(tmp_path):
    store = SelfEditStore(tmp_path)
    agents = store.load_agents()
    assert list(agents) == ["DEF", "PLN"]
    assert agents["DEF"].prompt_path is not None
    assert agents["DEF"].prompt_path.exists()
    assert agents["DEF"].allowed_tools == []
    assert agents["PLN"].prompt_path is not None
    assert agents["PLN"].prompt_path.exists()
    assert agents["PLN"].allowed_tools == ["read", "glob", "grep"]

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


def test_agent_profile_tool_config_roundtrip(tmp_path):
    store = SelfEditStore(tmp_path)
    profile = AgentProfile(
        id="TST",
        name="Test",
        prompt="test prompt",
        provider="copilot",
        model="gpt-4",
        allowed_tools=["read", "write"],
        tool_config={
            "bash": ToolConfig(policy="confirm", param_restrictions={"working_dir": "/tmp"}),
        },
    )
    store.save_agent(profile, "project")
    loaded = store.load_agents()
    assert "TST" in loaded
    assert loaded["TST"].tool_config["bash"].policy == "confirm"
    assert loaded["TST"].tool_config["bash"].param_restrictions == {"working_dir": "/tmp"}


def test_delete_agent_removes_row_and_prompt_file(tmp_path):
    store = SelfEditStore(tmp_path)
    profile = AgentProfile(
        id="TST",
        name="Test",
        prompt="test prompt",
        provider="copilot",
        model="gpt-4",
        allowed_tools=[],
    )
    store.save_agent(profile, "project")
    assert "TST" in store.load_agents()

    store.delete_agent("TST", "project")

    loaded = store.load_agents()
    assert "TST" not in loaded
    assert not (tmp_path / ".taui" / "self_edit" / "agents" / "TST.md").exists()


# ── AgentLoop tests ────────────────────────────────────────────────────


def test_agent_loop_pause_resume():
    import asyncio

    loop = AgentLoop.__new__(AgentLoop)
    loop._paused = asyncio.Event()
    loop._paused.set()

    assert not loop.is_paused
    loop.pause()
    assert loop.is_paused
    loop.resume()
    assert not loop.is_paused


def test_agent_loop_update_system_prompt():
    loop = AgentLoop.__new__(AgentLoop)
    loop._system_prompt = "old prompt"
    loop._messages = [Message(role="system", content="old prompt")]

    loop.update_system_prompt("new prompt")
    assert loop._system_prompt == "new prompt"
    assert loop._messages[0].content == "new prompt"


# ── PathAllowlist tests ────────────────────────────────────────────────


def test_path_allowlist_allows_config_dirs(tmp_path):
    allowlist = PathAllowlist(roots=(tmp_path / "config",))
    target = tmp_path / "config" / "sub" / "file.json"
    target.parent.mkdir(parents=True)
    target.touch()
    assert allowlist.allows(target)


def test_path_allowlist_allows_root_itself(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    allowlist = PathAllowlist(roots=(root,))
    assert allowlist.allows(root)


def test_path_allowlist_blocks_outside_paths(tmp_path):
    allowlist = PathAllowlist(roots=(tmp_path / "config",))
    outside = tmp_path / "other" / "file.txt"
    outside.parent.mkdir(parents=True)
    outside.touch()
    assert not allowlist.allows(outside)


def test_path_allowlist_symlink_escape_blocked(tmp_path):
    allowed = tmp_path / "config"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret")
    link = allowed / "link.txt"
    link.symlink_to(secret)

    allowlist = PathAllowlist(roots=(allowed,))
    # The symlink resolves to outside — must be blocked
    assert not allowlist.allows(link)


# ── load_self_edit_system_prompt tests ───────────────────────────────


def test_load_self_edit_system_prompt_mentions_categories():
    prompt = load_self_edit_system_prompt().lower()
    for category in ("agents", "tools", "skills", "mcp", "extensions", "providers", "commands"):
        assert category in prompt, f"Expected '{category}' in self-edit system prompt"


def test_build_self_edit_system_prompt_includes_active_cwd_and_relative_paths(tmp_path):
    SelfEditStore(tmp_path).save_default_scope("project")

    prompt = build_self_edit_system_prompt(tmp_path)

    assert "Active scope for new agents: **project**" in prompt
    assert f"Tool working directory: `{tmp_path / '.taui'}`" in prompt
    assert "Relative paths resolve from the **project** tool working directory." in prompt
    assert "`commands/`" in prompt
    assert "Do not prefix these with `.taui/`" in prompt


# ── build_scoped_tool_registry tests ──────────────────────────────────


class _FakeTool:
    name: str
    description: str = "fake"
    category = ToolCategory.FILE_READ
    schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("ok")


def _registry_with(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for name in names:
        reg.register(_FakeTool(name))
    return reg


def test_build_scoped_tool_registry_includes_only_expected_tools():
    base = _registry_with("read", "edit", "write", "bash", "git", "grep", "glob")
    scoped = build_scoped_tool_registry(base)
    assert set(scoped.names) == {"read", "edit", "write", "bash"}


def test_build_scoped_tool_registry_uses_fresh_tools_not_shared():
    # The scoped registry always contains the four self-edit tools as fresh instances,
    # independent of whatever is in the base registry.
    base = _registry_with()
    scoped = build_scoped_tool_registry(base)
    assert set(scoped.names) == {"read", "edit", "write", "bash"}


async def test_scoped_registry_resolves_relative_paths_from_project_scope(tmp_path):
    base = _registry_with()
    scoped = build_scoped_tool_registry(base, tmp_path, scope="project")

    result = await scoped.get("write").execute({
        "path": "extensions/example.py",
        "content": "x = 1\n",
    })

    assert not result.error
    assert (tmp_path / ".taui" / "extensions" / "example.py").read_text(
        encoding="utf-8"
    ) == "x = 1\n"


async def test_scoped_registry_allows_global_root_from_project_scope(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    base = _registry_with()
    scoped = build_scoped_tool_registry(base, tmp_path / "project", scope="project")

    result = await scoped.get("write").execute({
        "path": str(home / ".taui" / "extensions" / "global.py"),
        "content": "x = 1\n",
    })

    assert not result.error
    assert (home / ".taui" / "extensions" / "global.py").exists()


async def test_self_edit_executor_auto_approves_write_tools(tmp_path):
    SelfEditStore(tmp_path).save_default_scope("project")
    base = _registry_with()
    base_executor = ToolExecutor(
        registry=base,
        policy=ToolPolicy({"write": PolicyDecision.CONFIRM}),
    )
    executor = build_self_edit_executor(base, base_executor, tmp_path)

    outcome = await executor.run(
        "call_1",
        "write",
        {"path": "extensions/example.py", "content": "x = 1\n"},
    )

    assert isinstance(outcome, Completed)
    assert not isinstance(outcome, NeedsApproval)
    assert not outcome.result.error


async def test_scoped_bash_runs_from_project_scope(tmp_path):
    base = _registry_with()
    scoped = build_scoped_tool_registry(base, tmp_path, scope="project")

    result = await scoped.get("bash").execute({"command": "pwd"})

    assert not result.error
    assert result.content.strip() == str(tmp_path / ".taui")


async def test_scoped_bash_rejects_write_commands(tmp_path):
    base = _registry_with()
    scoped = build_scoped_tool_registry(base, tmp_path, scope="project")

    result = await scoped.get("bash").execute({"command": "touch outside.txt"})

    assert result.error
    assert "bash is read-only" in result.content


# ── wrap_tool_with_allowlist tests ────────────────────────────────────


async def test_wrap_tool_blocks_outside_path(tmp_path):
    allowed = tmp_path / "config"
    allowed.mkdir()
    allowlist = PathAllowlist(roots=(allowed,))
    tool = _FakeTool("read")
    wrapped = wrap_tool_with_allowlist(tool, allowlist)

    result = await wrapped.execute({"path": str(tmp_path / "outside" / "file.txt")})
    assert result.error
    assert "not in allowed config directories" in result.content


async def test_wrap_tool_allows_inside_path(tmp_path):
    allowed = tmp_path / "config"
    allowed.mkdir()
    inside = allowed / "file.txt"
    inside.write_text("data")
    allowlist = PathAllowlist(roots=(allowed,))
    tool = _FakeTool("read")
    wrapped = wrap_tool_with_allowlist(tool, allowlist)

    result = await wrapped.execute({"path": str(inside)})
    assert not result.error


async def test_wrap_tool_no_path_arg_passes_through(tmp_path):
    allowed = tmp_path / "config"
    allowed.mkdir()
    allowlist = PathAllowlist(roots=(allowed,))
    tool = _FakeTool("bash")
    wrapped = wrap_tool_with_allowlist(tool, allowlist)

    result = await wrapped.execute({"command": "ls"})
    assert not result.error


async def test_scoped_registry_does_not_mutate_base_tools(tmp_path):
    """Wrapping must NOT mutate the shared base-registry tool's execute method."""
    base = _registry_with("read")

    scoped = build_scoped_tool_registry(base)
    # Scoped tool refuses out-of-scope paths
    result = await scoped.get("read").execute({"path": str(tmp_path / "out" / "x")})
    assert result.error and "not in allowed config directories" in result.content

    # But the base registry's tool still accepts any path
    base_result = await base.get("read").execute({"path": "anything"})
    assert not base_result.error


# ── Session integration: /i command routing ────────────────────────────


async def test_handle_command_routes_slash_i_to_session_toggle(tmp_path):
    """`/i <msg>` must call session.toggle_self_edit_mode() and _send_and_drain."""
    from unittest.mock import MagicMock

    from taui.tui import TauiApp

    app = TauiApp(Config(working_dir=tmp_path))

    class FakeSession:
        self_edit_mode = False

        async def toggle_self_edit_mode(self) -> bool:
            self.self_edit_mode = True
            return True

    fake_session = FakeSession()
    app._session = fake_session  # type: ignore[assignment]
    app._wire_callbacks = MagicMock()
    app._update_status = MagicMock()
    app._send_and_drain = MagicMock()

    async with app.run_test():
        await app._handle_command("/i create agent QUI for research")

    assert fake_session.self_edit_mode is True
    app._send_and_drain.assert_called_once_with("create agent QUI for research")


# ── Session.switch_self_edit_scope ────────────────────────────────────


async def test_switch_self_edit_scope_flips_persists_and_rebuilds(tmp_path):
    """switch_self_edit_scope flips scope, persists to disk, and rebinds the loop."""
    from types import SimpleNamespace

    from taui.self_edit.scoping import _ScopedTool
    from taui.session import Session

    SelfEditStore(tmp_path).save_default_scope("global")

    base = _registry_with()
    base_executor = ToolExecutor(registry=base, policy=ToolPolicy())

    session = Session.__new__(Session)
    session.config = SimpleNamespace(working_dir=tmp_path)
    session._registry = base
    session._executor = base_executor
    session.self_edit_mode = True
    session._self_edit_scope = "global"
    session._self_edit_prompt = build_self_edit_system_prompt(tmp_path)
    session._self_edit_executor = build_self_edit_executor(
        base, base_executor, tmp_path
    )
    session._loop = SimpleNamespace(
        _executor=session._self_edit_executor,
        prompt_updates=[],
    )
    session._loop.update_system_prompt = session._loop.prompt_updates.append

    new_scope = await session.switch_self_edit_scope()

    assert new_scope == "project"
    assert session._self_edit_scope == "project"
    assert SelfEditStore(tmp_path).load_default_scope() == "project"
    assert session._loop._executor is session._self_edit_executor
    assert session._loop.prompt_updates == [session._self_edit_prompt]
    assert "Active scope for new agents: **project**" in session._self_edit_prompt
    bash_tool = session._self_edit_executor.registry.get("bash")
    assert isinstance(bash_tool, _ScopedTool)
    assert bash_tool._relative_root == tmp_path / ".taui"


async def test_switch_self_edit_scope_noop_when_not_in_self_edit(tmp_path):
    from types import SimpleNamespace

    from taui.session import Session

    session = Session.__new__(Session)
    session.config = SimpleNamespace(working_dir=tmp_path)
    session.self_edit_mode = False
    session._self_edit_scope = ""

    result = await session.switch_self_edit_scope()
    assert result == ""
