from __future__ import annotations

import asyncio
import json

from taui.agent.loop import AgentLoop
from taui.agent.types import Message
from taui.config import Config
from taui.self_edit.store import (
    AgentProfile,
    ExtensionSource,
    SelfEditStore,
    ToolConfig,
)
from taui.tools.registry import ToolRegistry
from taui.tui.widgets.self_edit_panel import SelfEditPanel

# ── Store tests ────────────────────────────────────────────────────────


def test_self_edit_scope_roundtrip(tmp_path):
    store = SelfEditStore(tmp_path)
    assert store.load_default_scope() == "global"
    store.save_default_scope("global")
    assert store.load_default_scope() == "global"


def test_agents_include_defaults_and_save_prompt_file(tmp_path):
    store = SelfEditStore(tmp_path)
    agents = store.load_agents()
    assert list(agents) == ["DEF"]
    assert agents["DEF"].prompt_path is not None
    assert agents["DEF"].prompt_path.exists()
    assert agents["DEF"].allowed_tools == []

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


# ── Self-edit panel tests ─────────────────────────────────────────────


async def test_self_edit_help_renders_inside_panel(tmp_path):
    panel = SelfEditPanel(
        Config(working_dir=tmp_path),
        SelfEditStore(tmp_path),
        ToolRegistry(),
    )
    panel.reload()

    await panel.run_verb("/help")

    markup = panel._panel_markup()
    assert "[bold #f0c808]/help[/bold #f0c808]" in markup
    assert '/agent new "reviewer"' in markup
    assert "AGENTS" in markup


# ── AgentLoop tests ────────────────────────────────────────────────────


def test_agent_loop_pause_resume():
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
