"""
Tests for Phase 5: Persistence & Recovery.

Coverage:
- startup_recovery marks interrupted sessions as 'stopped'
- startup_recovery restores event buffers from agent_events table
- startup_recovery dismisses pending questions
- startup_recovery releases orphaned branch locks
- startup_recovery emits a 'state_change/stopped' event into the buffer
- Sessions already in 'done' or 'stopped' state are not touched
- subscribe() on a recovered (non-running) agent returns the restored backlog
- list_agent_sessions_by_states returns only matching sessions
- list_branch_locks_for_agent returns only that agent's locks
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from taui.agent.manager import AgentManager
from taui.agent.runner import AgentEvent
from taui.specs.db import SpecDB

pytestmark = pytest.mark.anyio


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _make_db(tmp_path: Path) -> SpecDB:
    db = SpecDB(tmp_path, db_path=tmp_path / "test.db", persist_snapshot=False)
    await db.connect()
    return db


async def _seed_interrupted_session(
    db: SpecDB,
    *,
    agent_id: str = "agent-interrupted",
    spec_ref: str = "specs/core.md#core",
    state: str = "running",
    n_events: int = 3,
) -> None:
    """Create a session in the DB that simulates a mid-run agent at restart time."""
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=f"session-{agent_id}",
        spec_ref=spec_ref,
        task="Do something.",
        tier="mid",
    )
    await db.update_agent_state(agent_id, state)

    for i in range(n_events):
        await db.add_agent_event(
            agent_id=agent_id,
            event_type="state_change" if i == 0 else "tool_call",
            payload=json.dumps({"seq": i, "state": state}),
        )


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def test_list_sessions_by_states_filters_correctly(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)

    await db.create_agent_session(
        agent_id="a1",
        session_id="s1",
        spec_ref="x",
        task="t",
        tier="mid",
    )
    await db.update_agent_state("a1", "running")

    await db.create_agent_session(
        agent_id="a2",
        session_id="s2",
        spec_ref="x",
        task="t",
        tier="mid",
    )
    await db.update_agent_state("a2", "done")

    await db.create_agent_session(
        agent_id="a3",
        session_id="s3",
        spec_ref="x",
        task="t",
        tier="mid",
    )
    await db.update_agent_state("a3", "thinking")

    running_or_thinking = await db.list_agent_sessions_by_states(
        {"running", "thinking"}
    )
    ids = {r["agent_id"] for r in running_or_thinking}
    assert ids == {"a1", "a3"}

    done_only = await db.list_agent_sessions_by_states({"done"})
    assert [r["agent_id"] for r in done_only] == ["a2"]

    empty = await db.list_agent_sessions_by_states(set())
    assert empty == []

    await db.close()


async def test_list_branch_locks_for_agent(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)

    await db.create_agent_session(
        agent_id="ag1",
        session_id="s1",
        spec_ref="x",
        task="t",
        tier="mid",
    )
    await db.create_agent_session(
        agent_id="ag2",
        session_id="s2",
        spec_ref="x",
        task="t",
        tier="mid",
    )

    await db.acquire_branch_lock("specs/root", "ag1")
    await db.acquire_branch_lock("specs/child", "ag1")
    await db.acquire_branch_lock("specs/other", "ag2")

    ag1_locks = await db.list_branch_locks_for_agent("ag1")
    assert {r["spec_ref"] for r in ag1_locks} == {"specs/root", "specs/child"}

    ag2_locks = await db.list_branch_locks_for_agent("ag2")
    assert {r["spec_ref"] for r in ag2_locks} == {"specs/other"}

    await db.close()


# ── startup_recovery ───────────────────────────────────────────────────────────


async def test_startup_recovery_marks_sessions_stopped(tmp_path: Path) -> None:
    """Interrupted sessions are set to 'stopped' in the DB."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag-run", state="running")
    await _seed_interrupted_session(db, agent_id="ag-think", state="thinking")
    # Already done — should NOT be touched
    await _seed_interrupted_session(db, agent_id="ag-done", state="done", n_events=1)

    manager = AgentManager(db)
    await manager.startup_recovery()

    row_run = await db.get_agent_session("ag-run")
    row_think = await db.get_agent_session("ag-think")
    row_done = await db.get_agent_session("ag-done")

    assert row_run is not None and row_run["state"] == "stopped"
    assert row_think is not None and row_think["state"] == "stopped"
    # 'done' session untouched
    assert row_done is not None and row_done["state"] == "done"

    await db.close()


async def test_startup_recovery_restores_event_buffers(tmp_path: Path) -> None:
    """Event buffers are populated from agent_events table for recovered sessions."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag1", state="running", n_events=4)

    manager = AgentManager(db)
    await manager.startup_recovery()

    # Buffer should have 4 original events + 1 synthetic 'stopped' event
    buf = manager.get_buffered_events("ag1")
    assert len(buf) == 5  # 4 originals + 1 recovery event

    # Last event is the synthetic state_change/stopped
    last = buf[-1]
    assert last.event_type == "state_change"
    assert last.payload["state"] == "stopped"
    assert last.payload.get("reason") == "server_restart"

    await db.close()


async def test_startup_recovery_dismisses_pending_questions(tmp_path: Path) -> None:
    """Pending questions are dismissed during recovery."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag-q", state="running")

    await db.add_agent_question(
        agent_id="ag-q",
        question_node_ref="specs/core.md#q1",
        question="What should I do?",
    )
    await db.add_agent_question(
        agent_id="ag-q",
        question_node_ref="specs/core.md#q2",
        question="Another question?",
    )

    pending_before = await db.get_pending_questions("ag-q")
    assert len(pending_before) == 2

    manager = AgentManager(db)
    await manager.startup_recovery()

    pending_after = await db.get_pending_questions("ag-q")
    assert pending_after == []

    await db.close()


async def test_startup_recovery_releases_branch_locks(tmp_path: Path) -> None:
    """Branch locks held by interrupted agents are released."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag-lock", state="running")

    await db.acquire_branch_lock("specs/branch-a", "ag-lock")
    await db.acquire_branch_lock("specs/branch-b", "ag-lock")

    locks_before = await db.list_branch_locks_for_agent("ag-lock")
    assert len(locks_before) == 2

    manager = AgentManager(db)
    await manager.startup_recovery()

    locks_after = await db.list_branch_locks_for_agent("ag-lock")
    assert locks_after == []

    await db.close()


async def test_startup_recovery_no_interrupted_sessions(tmp_path: Path) -> None:
    """Recovery with no interrupted sessions is a no-op."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag-d", state="done", n_events=2)

    manager = AgentManager(db)
    await manager.startup_recovery()  # must not raise

    # Buffer not populated for done sessions
    buf = manager.get_buffered_events("ag-d")
    assert buf == []

    await db.close()


async def test_startup_recovery_persists_recovery_event(tmp_path: Path) -> None:
    """The synthetic recovery event is written to agent_events in the DB."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(db, agent_id="ag-p", state="running", n_events=2)

    manager = AgentManager(db)
    await manager.startup_recovery()

    all_events = await db.get_agent_events("ag-p")
    # 2 original + 1 recovery
    assert len(all_events) == 3
    last_ev = all_events[-1]
    assert last_ev["event_type"] == "state_change"
    payload = json.loads(last_ev["payload"])
    assert payload["state"] == "stopped"
    assert payload.get("reason") == "server_restart"

    await db.close()


async def test_subscribe_after_recovery_returns_backlog(tmp_path: Path) -> None:
    """subscribe() on a recovered agent returns the restored event backlog."""
    db = await _make_db(tmp_path)
    await _seed_interrupted_session(
        db, agent_id="ag-sub", state="tool_execution", n_events=5
    )

    manager = AgentManager(db)
    await manager.startup_recovery()

    backlog = manager.subscribe("ag-sub")
    # 5 originals + 1 recovery event
    assert len(backlog) == 6
    # Last event is the recovery state_change
    assert backlog[-1]["type"] == "state_change"
    assert backlog[-1]["state"] == "stopped"

    manager.unsubscribe("ag-sub")
    await db.close()


async def test_startup_recovery_handles_all_interrupted_states(tmp_path: Path) -> None:
    """All non-terminal states are recovered (idle, running, thinking, tool_execution, stopping)."""
    db = await _make_db(tmp_path)

    interrupted_states = ["idle", "running", "thinking", "tool_execution", "stopping"]
    for i, state in enumerate(interrupted_states):
        await _seed_interrupted_session(db, agent_id=f"ag-{i}", state=state, n_events=1)

    manager = AgentManager(db)
    await manager.startup_recovery()

    for i, state in enumerate(interrupted_states):
        row = await db.get_agent_session(f"ag-{i}")
        assert row is not None, f"Session ag-{i} not found"
        assert row["state"] == "stopped", (
            f"Expected 'stopped' for previously-{state!r} agent, got {row['state']!r}"
        )

    await db.close()
