"""
Tests for Phase 2: Agents can run and be observed.

Coverage:
- AgentRunner lifecycle (start → done)
- AgentRunner with tool execution via NoOp and real spec-tree tools
- AgentManager launch / stop / list
- DB persistence: agent sessions, messages, events, tool calls/results
- agent/launch, agent/stop, agent/list RPC handlers via WebSocket
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from taui.agent.manager import AgentManager
from taui.agent.runner import AgentRunner, AgentState, AgentEvent
from taui.llms.base import ProviderTurnResult, ProviderToolCall
from taui.specs.db import SpecDB
from taui.tools.registry import ToolRegistry

pytestmark = pytest.mark.anyio


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Agentic Coding Interface.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core intent.",
                "",
                "    - ## Leaf",
                "        Leaf intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_noop_llm() -> Any:
    """LLM stub: always returns no tool calls (agent finishes in one turn)."""
    from taui.server.handlers import _NoOpLLMClient

    return _NoOpLLMClient()


def _make_one_tool_llm(tool_name: str, arguments: dict[str, Any]) -> Any:
    """LLM stub: makes one tool call then stops on the next turn."""
    call_count = 0

    class _OnceToolLLM:
        async def create_turn(self, messages, model, tools=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ProviderTurnResult(
                    response_id="r1",
                    text="",
                    tool_calls=[
                        ProviderToolCall(
                            call_id="call-1",
                            name=tool_name,
                            arguments=arguments,
                        )
                    ],
                )
            return ProviderTurnResult(
                response_id="r2",
                text="Done.",
                tool_calls=[],
            )

    return _OnceToolLLM()


async def _make_db(tmp_path: Path) -> SpecDB:
    db = SpecDB(tmp_path, db_path=tmp_path / "test.db", persist_snapshot=False)
    await db.connect()
    return db


async def _run_runner(runner: AgentRunner, timeout: float = 5.0) -> None:
    """Start runner and wait for its background task to complete."""
    runner.start()
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=timeout)


# ── AgentRunner lifecycle ──────────────────────────────────────────────────────


async def test_agent_runner_completes_with_noop_llm(tmp_path: Path) -> None:
    """Runner finishes cleanly when LLM returns no tool calls."""
    db = await _make_db(tmp_path)
    registry = ToolRegistry()

    await db.create_agent_session(
        agent_id="agent-1",
        session_id="session-1",
        spec_ref="specs/core.md#core",
        task="Summarise the spec.",
        tier="mid",
        model="noop",
    )

    runner = AgentRunner(
        agent_id="agent-1",
        session_id="session-1",
        spec_ref="specs/core.md#core",
        task="Summarise the spec.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        db=db,
        tool_registry=registry,
    )

    events: list[AgentEvent] = []
    runner.event_callback = events.append

    await _run_runner(runner)
    await db.close()

    assert runner.state == AgentState.DONE
    state_events = [e for e in events if e.event_type == "state_change"]
    states = [e.payload["state"] for e in state_events]
    assert "running" in states
    assert "done" in states


async def test_agent_runner_persists_session_and_messages(tmp_path: Path) -> None:
    """Runner stores agent session and messages in DB."""
    db = await _make_db(tmp_path)
    registry = ToolRegistry()

    agent_id = "agent-persist"
    session_id = "session-persist"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Test task.",
        tier="mid",
        model="noop",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Test task.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        db=db,
        tool_registry=registry,
    )

    await _run_runner(runner)

    row = await db.get_agent_session(agent_id)
    assert row is not None
    assert row["state"] == "done"

    messages = await db._all(
        "SELECT * FROM agent_messages WHERE agent_id = ? ORDER BY seq",
        (agent_id,),
    )
    assert len(messages) >= 2
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "assistant" in roles
    await db.close()


async def test_agent_runner_stop_safely(tmp_path: Path) -> None:
    """stop_safely() requests shutdown and runner ends in DONE state."""
    db = await _make_db(tmp_path)

    class _SlowLLM:
        async def create_turn(self, messages, model, tools=None, **kwargs):
            await asyncio.sleep(0.05)
            return ProviderTurnResult(response_id=None, text="ok", tool_calls=[])

    agent_id = "agent-stop"
    session_id = "session-stop"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Stop me.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Stop me.",
        tier="mid",
        llm=_SlowLLM(),
        model="slow",
        db=db,
        tool_registry=ToolRegistry(),
    )

    runner.start()
    await asyncio.sleep(0.01)
    await runner.stop_safely()
    await db.close()

    assert runner.state == AgentState.DONE


# ── AgentRunner with tool execution ───────────────────────────────────────────


async def test_agent_runner_executes_unknown_tool_gracefully(tmp_path: Path) -> None:
    """Unknown tool name results in error but agent continues and finishes."""
    db = await _make_db(tmp_path)
    registry = ToolRegistry()  # empty — no tools registered

    agent_id = "agent-unknown-tool"
    session_id = "session-ut"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Run unknown tool.",
        tier="mid",
    )

    events: list[AgentEvent] = []

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Run unknown tool.",
        tier="mid",
        llm=_make_one_tool_llm("nonexistent_tool", {"x": 1}),
        model="test",
        db=db,
        tool_registry=registry,
        event_callback=events.append,
    )

    await _run_runner(runner)
    await db.close()

    assert runner.state == AgentState.DONE
    tool_events = [e for e in events if e.event_type in ("tool_call", "tool_result")]
    assert len(tool_events) == 2


async def test_agent_runner_persists_tool_call_and_result(tmp_path: Path) -> None:
    """Tool calls and results are persisted to DB tables."""
    db = await _make_db(tmp_path)

    from taui.tools.builtins.spec_tree import register_spec_tree_tools

    registry = ToolRegistry()
    register_spec_tree_tools(registry)

    agent_id = "agent-tool-persist"
    session_id = "session-tp"

    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Read spec tree.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Read spec tree.",
        tier="mid",
        llm=_make_one_tool_llm("spec_get_tree", {}),
        model="test",
        db=db,
        tool_registry=registry,
        spec_service=None,  # Tool will error — that's fine, we test persistence
    )

    await _run_runner(runner)

    assert runner.state == AgentState.DONE

    tool_calls = await db._all(
        "SELECT * FROM agent_tool_calls WHERE agent_id = ?", (agent_id,)
    )
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "spec_get_tree"

    tool_results = await db._all(
        "SELECT * FROM agent_tool_results WHERE call_id = ?",
        (tool_calls[0]["call_id"],),
    )
    assert len(tool_results) == 1
    await db.close()


# ── AgentManager ──────────────────────────────────────────────────────────────


async def test_agent_manager_launch_lists_active(tmp_path: Path) -> None:
    """Launched agent appears in list_active() or is already done."""
    db = await _make_db(tmp_path)
    manager = AgentManager(db=db)

    runner = await manager.launch(
        spec_ref="specs/core.md#core",
        task="Do something.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        tool_registry=ToolRegistry(),
    )

    # Agent may finish fast — check immediately after launch
    active = manager.list_active()
    # Either it's still in the active list or already done
    assert any(a["agent_id"] == runner.agent_id for a in active) or (
        runner.state == AgentState.DONE
    )

    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=5.0)
    await db.close()


async def test_agent_manager_stop_removes_runner(tmp_path: Path) -> None:
    """Stopped agent is removed from active list."""
    db = await _make_db(tmp_path)
    manager = AgentManager(db=db)

    class _SlowLLM:
        async def create_turn(self, messages, model, tools=None, **kwargs):
            await asyncio.sleep(10)
            return ProviderTurnResult(response_id=None, text="ok", tool_calls=[])

    runner = await manager.launch(
        spec_ref="specs/core.md#core",
        task="Run forever.",
        tier="mid",
        llm=_SlowLLM(),
        model="slow",
        tool_registry=ToolRegistry(),
    )

    assert runner.agent_id in manager._runners
    await manager.stop(runner.agent_id)
    assert runner.agent_id not in manager._runners
    await db.close()


async def test_agent_manager_events_forwarded_as_notifications(tmp_path: Path) -> None:
    """AgentManager forwards state_change events as agent/stateChanged notifications."""
    db = await _make_db(tmp_path)
    manager = AgentManager(db=db)

    notifications: list[dict[str, Any]] = []
    manager.set_notification_callback(notifications.append)

    runner = await manager.launch(
        spec_ref="specs/core.md#core",
        task="Quick task.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        tool_registry=ToolRegistry(),
    )

    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=5.0)
    await db.close()

    state_notifs = [n for n in notifications if n.get("method") == "agent/stateChanged"]
    assert len(state_notifs) > 0
    done_notifs = [
        n for n in state_notifs if n.get("params", {}).get("state") == "done"
    ]
    assert len(done_notifs) >= 1


# ── DB persistence: agent_events ──────────────────────────────────────────────


async def test_db_agent_events_persisted(tmp_path: Path) -> None:
    """Agent events are written to the agent_events table."""
    db = await _make_db(tmp_path)
    agent_id = "agent-events"
    session_id = "session-events"

    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#leaf",
        task="Events test.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#leaf",
        task="Events test.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        db=db,
        tool_registry=ToolRegistry(),
    )

    await _run_runner(runner)

    events = await db.get_agent_events(agent_id)
    await db.close()
    assert len(events) > 0
    event_types = {e["event_type"] for e in events}
    assert "state_change" in event_types


# ── spec-tree tools with real SpecService ─────────────────────────────────────


async def test_spec_tree_tool_reads_tree_with_real_service(tmp_path: Path) -> None:
    """spec_get_tree tool returns the spec tree when SpecService is injected."""
    _write_specs(tmp_path)

    from taui.specs.service import SpecService
    from taui.tools.builtins.spec_tree import SpecGetTreeTool
    from taui.tools.base import ToolContext
    from taui.config.policies import Policy
    from taui.config.settings import BashPolicySettings

    svc = SpecService(workspace=tmp_path)
    await svc.ensure_initialized()

    class _FakeSession:
        spec_service = svc

    policy = Policy(
        auto_approve=set(),
        confirm=set(),
        deny=set(),
        bash=BashPolicySettings(),
    )
    ctx = ToolContext(
        working_dir=tmp_path,
        session=_FakeSession(),
        policy=policy,
    )

    tool = SpecGetTreeTool()
    result = await tool.execute({}, ctx)
    await svc.db.close()

    assert not result.error, result.content
    data = json.loads(result.content)
    assert "nodes" in data
    assert len(data["nodes"]) > 0
    spec_refs = [n["spec_ref"] for n in data["nodes"]]
    assert any("core" in ref for ref in spec_refs)
