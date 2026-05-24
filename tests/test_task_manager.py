"""Smoke tests for the background TaskManager.

These exercise the lifecycle in isolation — no LLM, no Session — by
plugging a hand-written runner into the manager. The real Session wiring
in production assembles a sub-session runner; here we just verify the
state machine, persistence callbacks, and cancellation semantics.
"""
from __future__ import annotations

import asyncio

import pytest

from taui.tasks import TaskManager, TaskRecord, TaskState


async def _drained(records: list[TaskRecord]) -> None:
    # tiny helper so test reads as a sequence of state captures
    await asyncio.sleep(0)


class TestTaskManagerLifecycle:
    async def test_queued_to_running_to_done(self) -> None:
        seen: list[str] = []

        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            seen.append("runner_started")
            await asyncio.sleep(0.01)
            record.result = "OK"
            record.turns = 1

        mgr = TaskManager(runner=runner)
        states: list[str] = []
        mgr.set_state_listener(lambda r: states.append(r.state.value))

        record = await mgr.create(title="t", prompt="do thing")
        assert record.state == TaskState.QUEUED

        await mgr.wait_all(timeout=2.0)
        final = mgr.get(record.id)
        assert final is not None
        assert final.state == TaskState.DONE
        assert final.result == "OK"
        assert final.turns == 1
        assert seen == ["runner_started"]
        # We should see queued + running + done at minimum.
        assert "queued" in states
        assert "running" in states
        assert "done" in states

    async def test_failure_surfaces_error(self) -> None:
        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            raise RuntimeError("boom")

        mgr = TaskManager(runner=runner)
        record = await mgr.create(title="t", prompt="x")
        await mgr.wait_all(timeout=2.0)

        final = mgr.get(record.id)
        assert final is not None
        assert final.state == TaskState.FAILED
        assert "RuntimeError" in final.error
        assert "boom" in final.error

    async def test_stop_cancels_running_task(self) -> None:
        started = asyncio.Event()

        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            started.set()
            # Wait indefinitely for cancellation.
            await asyncio.sleep(30.0)

        mgr = TaskManager(runner=runner)
        record = await mgr.create(title="t", prompt="x")
        await asyncio.wait_for(started.wait(), timeout=1.0)

        ok = await mgr.stop(record.id)
        assert ok is True

        await mgr.wait_all(timeout=2.0)
        final = mgr.get(record.id)
        assert final is not None
        assert final.state == TaskState.CANCELLED

    async def test_stop_on_unknown_returns_false(self) -> None:
        mgr = TaskManager(runner=lambda r, c: asyncio.sleep(0))
        assert await mgr.stop("nope") is False

    async def test_update_blocked_after_run_starts(self) -> None:
        gate = asyncio.Event()

        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            await gate.wait()

        mgr = TaskManager(runner=runner)
        record = await mgr.create(title="orig", prompt="x")

        # Let the runner start.
        await asyncio.sleep(0.01)
        ok = await mgr.update(record.id, title="renamed")
        assert ok is False
        gate.set()
        await mgr.wait_all(timeout=2.0)

    async def test_list_returns_records_in_order(self) -> None:
        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            await asyncio.sleep(0.005)

        mgr = TaskManager(runner=runner)
        a = await mgr.create(title="a", prompt="x")
        b = await mgr.create(title="b", prompt="x")
        c = await mgr.create(title="c", prompt="x")

        ids = [r.id for r in mgr.list()]
        assert ids == [a.id, b.id, c.id]

        await mgr.wait_all(timeout=2.0)

    async def test_record_output_line_updates_last_output(self) -> None:
        gate = asyncio.Event()

        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            await mgr.record_output_line(record.id, "first")
            await mgr.record_output_line(record.id, "second")
            await gate.wait()

        mgr = TaskManager(runner=runner)
        record = await mgr.create(title="t", prompt="x")
        # Yield to the runner.
        await asyncio.sleep(0.05)
        assert mgr.get(record.id).last_output == "second"
        gate.set()
        await mgr.wait_all(timeout=2.0)


class TestTaskManagerWithoutRunner:
    async def test_create_requires_runner(self) -> None:
        mgr = TaskManager()
        with pytest.raises(RuntimeError):
            await mgr.create(title="t", prompt="x")


class TestTaskManagerPersistence:
    async def test_emits_task_events_to_stream(self) -> None:
        from taui.store.events import EventType

        emitted: list[tuple[str, dict]] = []

        class FakeStream:
            async def append(self, stream_id: str, event_type, data):
                emitted.append((event_type.value, data))
                return len(emitted)

        async def runner(record: TaskRecord, cancel: asyncio.Event) -> None:
            record.result = "fine"

        mgr = TaskManager(
            runner=runner,
            stream=FakeStream(),  # type: ignore[arg-type]
            parent_stream_id="agents/test",
        )
        record = await mgr.create(title="t", prompt="x")
        await mgr.wait_all(timeout=2.0)

        # At least: queued + running + done — possibly more for intermediate
        # state updates. Each one carries the TASK event type.
        assert len(emitted) >= 3
        for evt_type, _ in emitted:
            assert evt_type == EventType.TASK.value
        states_seen = [data["state"] for _, data in emitted]
        assert "queued" in states_seen
        assert "running" in states_seen
        assert "done" in states_seen
        assert all(data["id"] == record.id for _, data in emitted)
