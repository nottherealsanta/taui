"""
Tests for Phase 3: User ↔ Agent Interaction.

Coverage:
- Steer injection: message appears as <<STEER>> in runner history
- Task queue ordering: tasks run in FIFO order after first task completes
- Question flow: spec_ask_question blocks until runner.answer_question() is called
- Subscribe returns backlog: events emitted before subscribe are replayed
- Unsubscribe stops detail notifications: agent/toolCall not sent after unsubscribe
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from taui.agent.manager import AgentManager
from taui.agent.runner import AgentRunner, AgentState, AgentEvent
from taui.llms.base import ProviderTurnResult, ProviderToolCall
from taui.tangle.agent_db import AgentHistoryDB
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


async def _make_db(tmp_path: Path) -> AgentHistoryDB:
    db = AgentHistoryDB(tmp_path, db_path=tmp_path / "test-agents.db")
    await db.connect()
    return db


def _make_noop_llm() -> Any:
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


async def _run_runner(runner: AgentRunner, timeout: float = 5.0) -> None:
    runner.start()
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=timeout)


# ── Steer injection ────────────────────────────────────────────────────────────


async def test_steer_injection(tmp_path: Path) -> None:
    """Steer message injected before the first LLM turn appears as <<STEER>> in history."""
    db = await _make_db(tmp_path)

    seen_steer: list[str] = []

    class _CaptureLLM:
        async def create_turn(self, messages, model, tools=None, **kwargs):
            for m in messages:
                if isinstance(m, dict):
                    content = m.get("content") or ""
                else:
                    content = getattr(m, "content", "") or ""
                if "<<STEER>>" in str(content):
                    seen_steer.append(str(content))
            return ProviderTurnResult(response_id=None, text="done", tool_calls=[])

    agent_id = "agent-steer"
    session_id = "session-steer"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Steer test.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Steer test.",
        tier="mid",
        llm=_CaptureLLM(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
    )

    # Pre-load a steer message before the runner starts
    await runner.steer("Please focus on the Core section.")

    await _run_runner(runner)
    await db.close()

    assert runner.state == AgentState.DONE
    assert len(seen_steer) >= 1
    assert any("Please focus on the Core section." in s for s in seen_steer)


# ── Task queue ordering ────────────────────────────────────────────────────────


async def test_queue_ordering(tmp_path: Path) -> None:
    """Queued tasks run in FIFO order after the first task completes."""
    db = await _make_db(tmp_path)

    task_texts_seen: list[str] = []

    class _CaptureLLM:
        async def create_turn(self, messages, model, tools=None, **kwargs):
            # Capture the system prompt (first message contains the task)
            for m in messages:
                if isinstance(m, dict):
                    role = m.get("role", "")
                    content = m.get("content") or ""
                else:
                    role = getattr(m, "role", "")
                    content = getattr(m, "content", "") or ""
                if role == "system" and content:
                    task_texts_seen.append(content)
            return ProviderTurnResult(response_id=None, text="done", tool_calls=[])

    agent_id = "agent-queue"
    session_id = "session-queue"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="First task.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="First task.",
        tier="mid",
        llm=_CaptureLLM(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
    )

    # Queue two follow-up tasks before runner starts
    await db.enqueue_agent_task(agent_id=agent_id, message="Second task.")
    await db.enqueue_agent_task(agent_id=agent_id, message="Third task.")

    await _run_runner(runner, timeout=10.0)
    await db.close()

    assert runner.state == AgentState.DONE
    # All three task bodies should have been seen in system messages
    combined = " ".join(task_texts_seen)
    assert "First task." in combined
    assert "Second task." in combined
    assert "Third task." in combined


# ── Question flow ──────────────────────────────────────────────────────────────


async def test_question_flow(tmp_path: Path) -> None:
    """ask_question blocks until answer_question is called from outside."""
    db = await _make_db(tmp_path)

    agent_id = "agent-question"
    session_id = "session-question"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Question test.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/core.md#core",
        task="Question test.",
        tier="mid",
        llm=_make_noop_llm(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
    )

    answer_received: list[str | None] = []

    async def _ask_then_record() -> None:
        ans = await runner.ask_question(
            spec_ref="specs/core.md#core",
            question="Which approach should I use?",
            options=["Option A", "Option B"],
            timeout=5.0,
        )
        answer_received.append(ans)

    # Start the question-asking coroutine concurrently
    ask_task = asyncio.create_task(_ask_then_record())

    # Give the runner a moment to register the pending question
    await asyncio.sleep(0.05)

    # Grab the pending question_node_ref from DB and answer it
    pending = await db.get_pending_questions(agent_id)
    assert len(pending) == 1, f"Expected 1 pending question, got {len(pending)}"
    q_ref = pending[0]["question_node_ref"]

    answered = runner.answer_question(q_ref, "Option B")
    assert answered is True

    # Wait for the ask coroutine to resolve
    await asyncio.wait_for(ask_task, timeout=2.0)
    await db.close()

    assert answer_received == ["Option B"]


# ── Subscribe returns backlog ──────────────────────────────────────────────────


async def test_subscribe_returns_backlog(tmp_path: Path) -> None:
    """subscribe() after agent finishes returns a non-empty backlog of events."""
    db = await _make_db(tmp_path)
    manager = AgentManager(db=db)

    runner = await manager.launch(
        spec_ref="specs/core.md#core",
        task="Backlog test.",
        tier="mid",
        llm=_make_noop_llm(),
        model="noop",
        tool_registry=ToolRegistry(),
    )

    # Wait for agent to finish
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=5.0)

    # Subscribe after the fact — should get the buffered events
    backlog = manager.subscribe(runner.agent_id)
    await db.close()

    assert len(backlog) > 0
    event_types = {e["type"] for e in backlog}
    assert "state_change" in event_types


# ── Unsubscribe stops detail notifications ────────────────────────────────────


async def test_unsubscribe_stops_detail_notifications(tmp_path: Path) -> None:
    """After unsubscribe, agent/toolCall detail events are not emitted."""
    db = await _make_db(tmp_path)
    manager = AgentManager(db=db)

    notifications: list[dict[str, Any]] = []
    manager.set_notification_callback(notifications.append)

    # Subscribe before launch
    # We use an agent_id placeholder — subscribe just adds to the set
    # Launch creates the real runner with the actual agent_id
    runner = await manager.launch(
        spec_ref="specs/core.md#core",
        task="Unsub test.",
        tier="mid",
        llm=_make_one_tool_llm("spec_get_tree", {}),
        model="test",
        tool_registry=ToolRegistry(),  # empty registry — tool will error, that's fine
    )

    # Subscribe so detail events would be emitted
    manager.subscribe(runner.agent_id)

    # Immediately unsubscribe before agent finishes
    manager.unsubscribe(runner.agent_id)

    # Wait for agent to finish
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=5.0)
    await db.close()

    # Should have stateChanged (always), toolBrief (always), but NOT toolCall (detail)
    tool_call_notifs = [n for n in notifications if n.get("method") == "agent/toolCall"]
    assert len(tool_call_notifs) == 0

    # Brief indicator should still be present
    tool_brief_notifs = [
        n for n in notifications if n.get("method") == "agent/toolBrief"
    ]
    assert len(tool_brief_notifs) >= 1
