"""
TaskManager — owns an asyncio pool of background sub-session tasks.

Each background task spawns a child sub-session whose work proceeds
independently of the main agent loop. The parent agent fires off the task,
keeps responding, and can poll/inspect/cancel it via the task_* tools.

State transitions
─────────────────
    queued → running → done
                   ↘   failed
                   ↘   cancelled

The full transition stream is persisted by appending TASK events to the
parent stream, so tasks survive the lifetime of the Session object that
created them and can be replayed on resume.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from taui.store.events import EventType
from taui.store.stream import StreamClient

logger = logging.getLogger(__name__)


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    """Persisted snapshot of a background task's state."""

    id: str
    title: str
    prompt: str
    state: TaskState = TaskState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    stream_id: str | None = None
    last_output: str = ""
    result: str = ""
    error: str = ""
    tools: list[str] | None = None
    agent_id: str | None = None
    model: str | None = None
    max_turns: int = 10
    turns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "stream_id": self.stream_id,
            "last_output": self.last_output,
            "result": self.result,
            "error": self.error,
            "tools": self.tools,
            "agent_id": self.agent_id,
            "model": self.model,
            "max_turns": self.max_turns,
            "turns": self.turns,
        }


@dataclass
class BackgroundTask:
    """Live in-memory handle for a queued/running task."""

    record: TaskRecord
    asyncio_task: asyncio.Task[Any] | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


# Callback used by the manager to actually run a task. Receives the
# TaskRecord (mutable) and a cancel_event the runner should respect.
TaskRunner = Callable[[TaskRecord, asyncio.Event], Awaitable[None]]


class TaskManager:
    """Owns the asyncio pool of background tasks for a session.

    The manager is otherwise stateless about *how* tasks are executed —
    Session.create() injects a `runner` callback that knows how to spawn
    a sub-session and shuttle its output into the TaskRecord. This keeps
    the manager testable without needing a full LLM provider.
    """

    def __init__(
        self,
        *,
        stream: StreamClient | None = None,
        parent_stream_id: str | None = None,
        runner: TaskRunner | None = None,
        on_state_change: Callable[[TaskRecord], Awaitable[None] | None] | None = None,
    ) -> None:
        self._stream = stream
        self._parent_stream_id = parent_stream_id
        self._runner = runner
        self._on_state_change = on_state_change
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = asyncio.Lock()

    # ── Configuration ─────────────────────────────────────────────────────

    def set_runner(self, runner: TaskRunner) -> None:
        self._runner = runner

    def set_stream(self, stream: StreamClient, parent_stream_id: str) -> None:
        self._stream = stream
        self._parent_stream_id = parent_stream_id

    def set_state_listener(
        self,
        cb: Callable[[TaskRecord], Awaitable[None] | None] | None,
    ) -> None:
        self._on_state_change = cb

    # ── Public surface ────────────────────────────────────────────────────

    async def create(
        self,
        *,
        title: str,
        prompt: str,
        tools: list[str] | None = None,
        agent_id: str | None = None,
        model: str | None = None,
        max_turns: int = 10,
    ) -> TaskRecord:
        """Create a task and schedule it on the asyncio pool."""
        if self._runner is None:
            raise RuntimeError("TaskManager has no runner configured.")

        task_id = uuid4().hex[:8]
        record = TaskRecord(
            id=task_id,
            title=title,
            prompt=prompt,
            tools=tools,
            agent_id=agent_id,
            model=model,
            max_turns=max_turns,
        )
        bg = BackgroundTask(record=record)
        async with self._lock:
            self._tasks[task_id] = bg

        await self._emit(record)
        bg.asyncio_task = asyncio.create_task(self._drive(bg), name=f"task-{task_id}")
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        bg = self._tasks.get(task_id)
        return bg.record if bg else None

    def list(self) -> list[TaskRecord]:
        """Return all tasks in creation order."""
        return [bg.record for bg in self._tasks.values()]

    async def stop(self, task_id: str) -> bool:
        """Signal cancellation. Returns True if the task was running/queued."""
        bg = self._tasks.get(task_id)
        if bg is None:
            return False
        if bg.record.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED):
            return False
        bg.cancel_event.set()
        if bg.asyncio_task is not None and not bg.asyncio_task.done():
            bg.asyncio_task.cancel()
        return True

    async def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        prompt: str | None = None,
    ) -> bool:
        """Update mutable fields. Only honored while task is queued."""
        bg = self._tasks.get(task_id)
        if bg is None:
            return False
        if bg.record.state != TaskState.QUEUED:
            return False
        if title is not None:
            bg.record.title = title
        if prompt is not None:
            bg.record.prompt = prompt
        await self._emit(bg.record)
        return True

    async def wait_all(self, *, timeout: float | None = None) -> None:
        """Wait until every task has reached a terminal state."""
        pending = [
            bg.asyncio_task
            for bg in self._tasks.values()
            if bg.asyncio_task is not None and not bg.asyncio_task.done()
        ]
        if not pending:
            return
        await asyncio.wait(pending, timeout=timeout)

    async def shutdown(self) -> None:
        """Cancel any in-flight tasks and wait for them to settle."""
        for bg in self._tasks.values():
            if bg.asyncio_task is not None and not bg.asyncio_task.done():
                bg.cancel_event.set()
                bg.asyncio_task.cancel()
        await self.wait_all(timeout=2.0)

    # ── Helpers for the runner ────────────────────────────────────────────

    async def record_output_line(self, task_id: str, line: str) -> None:
        """Append a single line of streaming output to the task record.

        The runner uses this to report progress. We don't persist every
        line to the event store — that would be noisy — but we do keep
        the last line on the record and notify listeners.
        """
        bg = self._tasks.get(task_id)
        if bg is None:
            return
        bg.record.last_output = line
        await self._notify(bg.record)

    # ── Internal ──────────────────────────────────────────────────────────

    async def _drive(self, bg: BackgroundTask) -> None:
        record = bg.record
        record.state = TaskState.RUNNING
        record.started_at = time.time()
        await self._emit(record)
        try:
            assert self._runner is not None
            await self._runner(record, bg.cancel_event)
            if bg.cancel_event.is_set() and record.state == TaskState.RUNNING:
                record.state = TaskState.CANCELLED
            elif record.state == TaskState.RUNNING:
                record.state = TaskState.DONE
        except asyncio.CancelledError:
            record.state = TaskState.CANCELLED
            # Don't re-raise: cancellation here is the requested outcome.
        except Exception as exc:
            logger.exception("Background task %s failed", record.id)
            record.state = TaskState.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
        finally:
            record.ended_at = time.time()
            await self._emit(record)

    async def _emit(self, record: TaskRecord) -> None:
        await self._persist(record)
        await self._notify(record)

    async def _persist(self, record: TaskRecord) -> None:
        if self._stream is None or self._parent_stream_id is None:
            return
        try:
            await self._stream.append(
                self._parent_stream_id,
                EventType.TASK,
                record.to_dict(),
            )
        except Exception:
            logger.debug("Failed to persist task event", exc_info=True)

    async def _notify(self, record: TaskRecord) -> None:
        cb = self._on_state_change
        if cb is None:
            return
        try:
            result = cb(record)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.debug("Task state listener raised", exc_info=True)
