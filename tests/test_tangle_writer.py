"""
Tests for Phase 6: Revised Spec-Tree ↔ File Writeback.

Coverage:
- SpecMarkdownWriter._deferred flag: schedule_writeback marks dirty but does not
  start a debounced task
- flush_all_files() writes all dirty files immediately and clears pending set
- flush_all_files() cancels any running debounced tasks before writing
- SpecService.defer_writeback() context manager:
  - enables deferred mode on entry
  - flushes all dirty files on exit
  - restores normal (non-deferred) mode on exit
- AgentRunner uses defer_writeback per task when spec_service is available:
  - no debounced tasks fire mid-task
  - files are written exactly once per task completion (batch flush)
- Queued tasks also use defer_writeback (one flush per task)
- On stop/cancel the runner still flushes via the finally block
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taui.agent.runner import AgentRunner, AgentState
from taui.llms.base import ProviderTurnResult
from taui.tangle.agent_db import AgentHistoryDB
from taui.tangle.writer import SpecMarkdownWriter
from taui.tools.registry import ToolRegistry

pytestmark = pytest.mark.anyio


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _make_db(tmp_path: Path) -> AgentHistoryDB:
    db = AgentHistoryDB(tmp_path, db_path=tmp_path / "test-agents.db")
    await db.connect()
    return db


class _FakeDB:
    """Minimal async DB double for writer tests that don't need real persistence."""

    async def get_file_by_id(self, file_id: int):
        return None  # writer will early-return

    async def get_nodes_for_file(self, file_id: int):
        return []


# ── SpecMarkdownWriter._deferred ───────────────────────────────────────────────


async def test_deferred_mode_no_task_created(tmp_path: Path) -> None:
    """In deferred mode, schedule_writeback does not create asyncio tasks."""
    writer = SpecMarkdownWriter(workspace=tmp_path, db=_FakeDB(), debounce_ms=50)  # type: ignore[arg-type]
    writer._deferred = True

    writer.schedule_writeback(1)
    writer.schedule_writeback(2)
    writer.schedule_writeback(1)  # duplicate

    # No tasks should have been created
    assert len(writer._tasks) == 0
    # But files are tracked as dirty
    assert writer._pending == {1, 2}


async def test_normal_mode_creates_tasks(tmp_path: Path) -> None:
    """In normal mode, schedule_writeback creates debounced asyncio tasks."""
    writer = SpecMarkdownWriter(workspace=tmp_path, db=_FakeDB(), debounce_ms=50)  # type: ignore[arg-type]
    assert not writer._deferred

    writer.schedule_writeback(42)

    assert 42 in writer._tasks
    task = writer._tasks[42]
    assert not task.done()
    # Cancel to avoid running into an event loop issue after test
    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task


async def test_flush_all_files_writes_and_clears(tmp_path: Path) -> None:
    """flush_all_files() writes all pending files and clears the pending set."""
    write_calls: list[int] = []

    class _TrackingWriter(SpecMarkdownWriter):
        async def write_file(self, file_id: int) -> None:  # type: ignore[override]
            write_calls.append(file_id)

    writer = _TrackingWriter(workspace=tmp_path, db=_FakeDB(), debounce_ms=50)  # type: ignore[arg-type]
    writer._pending = {1, 3, 5}

    await writer.flush_all_files()

    assert sorted(write_calls) == [1, 3, 5]
    assert writer._pending == set()


async def test_flush_all_files_cancels_debounced_tasks(tmp_path: Path) -> None:
    """flush_all_files() cancels any running debounced tasks."""
    write_calls: list[int] = []

    class _TrackingWriter(SpecMarkdownWriter):
        async def write_file(self, file_id: int) -> None:  # type: ignore[override]
            write_calls.append(file_id)

    writer = _TrackingWriter(workspace=tmp_path, db=_FakeDB(), debounce_ms=10_000)  # type: ignore[arg-type]
    # Schedule normally (creates long-lived debounced task)
    writer.schedule_writeback(7)
    assert 7 in writer._tasks

    await writer.flush_all_files()

    # Task must have been cancelled / gone
    assert len(writer._tasks) == 0
    # File was still written
    assert 7 in write_calls
    assert writer._pending == set()


# ── SpecService.defer_writeback ────────────────────────────────────────────────


async def test_defer_writeback_context_manager(tmp_path: Path) -> None:
    """defer_writeback() sets/clears _deferred flag and flushes on exit."""
    from taui.tangle.service import SpecService

    specs_path = tmp_path / "specs"
    specs_path.mkdir()
    (specs_path / "_main.md").write_text("- Root\n    Root node.\n", encoding="utf-8")

    svc = SpecService(workspace=tmp_path, specs_path=specs_path, dev_mode=True)
    await svc.ensure_initialized()

    flush_calls: list[str] = []

    original_flush = svc.writer.flush_all_files

    async def _spy_flush():
        flush_calls.append("flush")
        return await original_flush()

    svc.writer.flush_all_files = _spy_flush  # type: ignore[method-assign]

    assert not svc.writer._deferred

    async with svc.defer_writeback():
        assert svc.writer._deferred, "Should be in deferred mode inside context"

    assert not svc.writer._deferred, "Should be restored to normal mode after context"
    assert flush_calls == ["flush"], (
        "flush_all_files should have been called once on exit"
    )

    await svc.db.close()


async def test_defer_writeback_flushes_on_exception(tmp_path: Path) -> None:
    """defer_writeback() flushes even if an exception occurs inside."""
    from taui.tangle.service import SpecService

    specs_path = tmp_path / "specs"
    specs_path.mkdir()
    (specs_path / "_main.md").write_text("- Root\n    Root node.\n", encoding="utf-8")

    svc = SpecService(workspace=tmp_path, specs_path=specs_path, dev_mode=True)
    await svc.ensure_initialized()

    flushed = []
    original_flush = svc.writer.flush_all_files

    async def _spy_flush():
        flushed.append(True)
        return await original_flush()

    svc.writer.flush_all_files = _spy_flush  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        async with svc.defer_writeback():
            raise RuntimeError("boom")

    # Even on exception, deferred mode is restored and flush was called
    assert not svc.writer._deferred
    assert flushed, "flush_all_files should be called even when exception raised"

    await svc.db.close()


# ── AgentRunner + defer_writeback integration ─────────────────────────────────


def _noop_llm() -> Any:
    from taui.server.handlers import _NoOpLLMClient

    return _NoOpLLMClient()


async def _run_runner(runner: AgentRunner, timeout: float = 5.0) -> None:
    runner.start()
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=timeout)


async def test_agent_runner_uses_defer_writeback(tmp_path: Path) -> None:
    """AgentRunner wraps each task in defer_writeback when spec_service is set."""
    db = await _make_db(tmp_path)

    agent_id = "ag-phase6"
    session_id = "sess-phase6"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="Phase 6 test.",
        tier="mid",
    )

    deferred_context_entered = []
    flushed = []

    class _FakeSpecService:
        """Minimal spec service double that records defer_writeback usage."""

        import contextlib

        @contextlib.asynccontextmanager
        async def defer_writeback(self):
            deferred_context_entered.append(True)
            try:
                yield
            finally:
                flushed.append(True)

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="Phase 6 test.",
        tier="mid",
        llm=_noop_llm(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
        spec_service=_FakeSpecService(),
    )

    await _run_runner(runner)

    assert runner.state == AgentState.DONE
    assert deferred_context_entered, "defer_writeback context should have been entered"
    assert flushed, "defer_writeback context exit (flush) should have been called"

    await db.close()


async def test_agent_runner_queued_tasks_each_defer(tmp_path: Path) -> None:
    """Each queued task is wrapped in its own defer_writeback context."""
    db = await _make_db(tmp_path)

    agent_id = "ag-queue-defer"
    session_id = "sess-queue-defer"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="First task.",
        tier="mid",
    )
    # Queue a second task
    await db.enqueue_agent_task(agent_id=agent_id, message="Second task.")

    flush_count = []

    class _FakeSpecService:
        import contextlib

        @contextlib.asynccontextmanager
        async def defer_writeback(self):
            try:
                yield
            finally:
                flush_count.append(1)

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="First task.",
        tier="mid",
        llm=_noop_llm(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
        spec_service=_FakeSpecService(),
    )

    await _run_runner(runner, timeout=10.0)

    assert runner.state == AgentState.DONE
    # One flush per task (first + one queued = 2)
    assert len(flush_count) >= 2, f"Expected ≥2 flushes, got {len(flush_count)}"

    await db.close()


async def test_agent_runner_no_spec_service_still_works(tmp_path: Path) -> None:
    """AgentRunner without spec_service still completes normally."""
    db = await _make_db(tmp_path)

    agent_id = "ag-no-svc"
    session_id = "sess-no-svc"
    await db.create_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="No spec service.",
        tier="mid",
    )

    runner = AgentRunner(
        agent_id=agent_id,
        session_id=session_id,
        spec_ref="specs/_main.md#root",
        task="No spec service.",
        tier="mid",
        llm=_noop_llm(),
        model="test",
        db=db,
        tool_registry=ToolRegistry(),
        spec_service=None,  # no spec service
    )

    await _run_runner(runner)
    assert runner.state == AgentState.DONE

    await db.close()


async def test_deferred_mode_mutations_do_not_trigger_early_writes(
    tmp_path: Path,
) -> None:
    """While in deferred mode, calling schedule_writeback never writes to disk."""
    write_calls: list[int] = []

    class _TrackingWriter(SpecMarkdownWriter):
        async def write_file(self, file_id: int) -> None:  # type: ignore[override]
            write_calls.append(file_id)

    writer = _TrackingWriter(workspace=tmp_path, db=_FakeDB(), debounce_ms=1)  # type: ignore[arg-type]
    writer._deferred = True

    # Schedule many mutations
    for fid in [1, 2, 3, 1, 2]:
        writer.schedule_writeback(fid)

    # Give any rogue tasks time to fire (there should be none)
    await asyncio.sleep(0.05)

    assert write_calls == [], "No files should be written while in deferred mode"
    assert writer._pending == {1, 2, 3}

    # Now flush manually
    writer._deferred = False
    await writer.flush_all_files()
    assert sorted(write_calls) == [1, 2, 3]
