"""Tests for taui.store — Store, StreamClient, and event types."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from taui.store import (
    Event,
    EventType,
    OffsetConflictError,
    Store,
    StreamClient,
    StreamClosedError,
    StreamNotFoundError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path)
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def client(store: Store):
    return StreamClient(store)


# ═══ Store lifecycle ═══════════════════════════════════════════════════════════


class TestStoreLifecycle:
    async def test_connect_creates_db(self, tmp_path: Path):
        store = Store(tmp_path)
        await store.connect()
        assert store.db_path.exists()
        await store.close()

    async def test_double_connect_is_idempotent(self, store: Store):
        await store.connect()  # already connected, should be no-op

    async def test_double_close_is_safe(self, tmp_path: Path):
        store = Store(tmp_path)
        await store.connect()
        await store.close()
        await store.close()  # second close is no-op


# ═══ Stream CRUD ══════════════════════════════════════════════════════════════


class TestStreamCRUD:
    async def test_create_stream(self, store: Store):
        assert await store.create_stream("agents/test-1") is True

    async def test_create_stream_idempotent(self, store: Store):
        await store.create_stream("agents/test-1")
        assert await store.create_stream("agents/test-1") is False

    async def test_stream_exists(self, store: Store):
        assert await store.stream_exists("agents/test-1") is False
        await store.create_stream("agents/test-1")
        assert await store.stream_exists("agents/test-1") is True

    async def test_create_stream_with_parent(self, store: Store):
        await store.create_stream("agents/parent")
        await store.create_stream("agents/child", parent_id="agents/parent")
        info = await store.get_stream_info("agents/child")
        assert info is not None
        assert info["parent_id"] == "agents/parent"

    async def test_get_stream_info(self, store: Store):
        await store.create_stream("agents/test-1")
        info = await store.get_stream_info("agents/test-1")
        assert info is not None
        assert info["stream_id"] == "agents/test-1"
        assert info["closed"] == 0
        assert info["length"] == 0

    async def test_get_stream_info_missing(self, store: Store):
        assert await store.get_stream_info("nope") is None

    async def test_close_stream(self, store: Store):
        await store.create_stream("agents/test-1")
        await store.close_stream("agents/test-1")
        assert await store.is_closed("agents/test-1") is True

    async def test_close_missing_stream_raises(self, store: Store):
        with pytest.raises(StreamNotFoundError):
            await store.close_stream("nope")

    async def test_is_closed_on_open_stream(self, store: Store):
        await store.create_stream("agents/test-1")
        assert await store.is_closed("agents/test-1") is False

    async def test_is_closed_on_missing_raises(self, store: Store):
        with pytest.raises(StreamNotFoundError):
            await store.is_closed("nope")


# ═══ Append ═══════════════════════════════════════════════════════════════════


class TestAppend:
    async def test_append_auto_offset(self, store: Store):
        await store.create_stream("s1")
        off0 = await store.append("s1", EventType.STATE_CHANGE, {"state": "running"})
        off1 = await store.append("s1", EventType.TOKEN, {"text": "hello"})
        assert off0 == 0
        assert off1 == 1

    async def test_append_explicit_offset(self, store: Store):
        await store.create_stream("s1")
        off = await store.append("s1", EventType.TOKEN, {"text": "hi"}, offset=0)
        assert off == 0

    async def test_append_idempotent_same_data(self, store: Store):
        await store.create_stream("s1")
        data = {"text": "hello"}
        await store.append("s1", EventType.TOKEN, data, offset=0)
        off = await store.append("s1", EventType.TOKEN, data, offset=0)
        assert off == 0
        # Should still only have one event
        assert await store.get_length("s1") == 1

    async def test_append_offset_conflict(self, store: Store):
        await store.create_stream("s1")
        await store.append("s1", EventType.TOKEN, {"text": "a"}, offset=0)
        with pytest.raises(OffsetConflictError):
            await store.append("s1", EventType.TOKEN, {"text": "b"}, offset=0)

    async def test_append_to_missing_stream(self, store: Store):
        with pytest.raises(StreamNotFoundError):
            await store.append("nope", EventType.TOKEN, {"text": "x"})

    async def test_append_to_closed_stream(self, store: Store):
        await store.create_stream("s1")
        await store.close_stream("s1")
        with pytest.raises(StreamClosedError):
            await store.append("s1", EventType.TOKEN, {"text": "x"})

    async def test_concurrent_append_unique_offsets(self, tmp_path: Path):
        s1 = Store(tmp_path)
        s2 = Store(tmp_path)
        await s1.connect()
        await s2.connect()
        try:
            await s1.create_stream("s1")

            async def write(store: Store, value: int) -> int:
                return await store.append("s1", EventType.TOKEN, {"i": value})

            offsets = await asyncio.gather(write(s1, 1), write(s2, 2))
            assert sorted(offsets) == [0, 1]
            events = await s1.read("s1")
            assert [event.offset for event in events] == [0, 1]
        finally:
            await s1.close()
            await s2.close()


# ═══ Read ═════════════════════════════════════════════════════════════════════


class TestRead:
    async def test_read_empty_stream(self, store: Store):
        await store.create_stream("s1")
        events = await store.read("s1")
        assert events == []

    async def test_read_returns_events_in_order(self, store: Store):
        await store.create_stream("s1")
        await store.append("s1", EventType.STATE_CHANGE, {"state": "running"})
        await store.append("s1", EventType.TOKEN, {"text": "hi"})
        await store.append("s1", EventType.TOKEN, {"text": "there"})

        events = await store.read("s1")
        assert len(events) == 3
        assert events[0].offset == 0
        assert events[0].type == EventType.STATE_CHANGE
        assert events[1].offset == 1
        assert events[2].offset == 2

    async def test_read_from_offset(self, store: Store):
        await store.create_stream("s1")
        for i in range(5):
            await store.append("s1", EventType.TOKEN, {"i": i})
        events = await store.read("s1", from_offset=3)
        assert len(events) == 2
        assert events[0].offset == 3
        assert events[1].offset == 4

    async def test_read_with_limit(self, store: Store):
        await store.create_stream("s1")
        for i in range(10):
            await store.append("s1", EventType.TOKEN, {"i": i})
        events = await store.read("s1", limit=3)
        assert len(events) == 3

    async def test_read_missing_stream_raises(self, store: Store):
        with pytest.raises(StreamNotFoundError):
            await store.read("nope")

    async def test_get_length(self, store: Store):
        await store.create_stream("s1")
        assert await store.get_length("s1") == 0
        await store.append("s1", EventType.TOKEN, {"text": "a"})
        await store.append("s1", EventType.TOKEN, {"text": "b"})
        assert await store.get_length("s1") == 2

    async def test_event_data_round_trip(self, store: Store):
        await store.create_stream("s1")
        data = {"nested": {"key": [1, 2, 3]}, "flag": True, "count": 42}
        await store.append("s1", EventType.STATE_CHANGE, data)
        events = await store.read("s1")
        assert events[0].data == data

    async def test_stream_info_length_updates(self, store: Store):
        await store.create_stream("s1")
        await store.append("s1", EventType.TOKEN, {"text": "a"})
        await store.append("s1", EventType.TOKEN, {"text": "b"})
        info = await store.get_stream_info("s1")
        assert info["length"] == 2


# ═══ Live-tail ════════════════════════════════════════════════════════════════


class TestLiveTail:
    async def test_wait_wakes_on_append(self, store: Store):
        await store.create_stream("s1")

        async def writer():
            await asyncio.sleep(0.05)
            await store.append("s1", EventType.TOKEN, {"text": "wake"})

        task = asyncio.create_task(writer())
        got = await store.wait_for_new("s1", timeout=2.0)
        assert got is True
        await task

    async def test_wait_times_out(self, store: Store):
        await store.create_stream("s1")
        got = await store.wait_for_new("s1", timeout=0.05)
        assert got is False

    async def test_close_wakes_waiters(self, store: Store):
        await store.create_stream("s1")

        async def closer():
            await asyncio.sleep(0.05)
            await store.close_stream("s1")

        task = asyncio.create_task(closer())
        got = await store.wait_for_new("s1", timeout=2.0)
        assert got is True
        await task


# ═══ StreamClient ═════════════════════════════════════════════════════════════


class TestStreamClient:
    async def test_ensure_stream(self, client: StreamClient, store: Store):
        await client.ensure_stream("s1")
        assert await store.stream_exists("s1") is True

    async def test_ensure_stream_idempotent(self, client: StreamClient):
        await client.ensure_stream("s1")
        await client.ensure_stream("s1")  # no error

    async def test_ensure_stream_with_parent(self, client: StreamClient, store: Store):
        await client.ensure_stream("parent")
        await client.ensure_stream("child", parent_id="parent")
        info = await store.get_stream_info("child")
        assert info["parent_id"] == "parent"

    async def test_close_stream(self, client: StreamClient, store: Store):
        await client.ensure_stream("s1")
        await client.close_stream("s1")
        assert await store.is_closed("s1") is True

    async def test_close_missing_stream_no_error(self, client: StreamClient):
        await client.close_stream("nope")  # logs warning, no error

    async def test_append_and_read(self, client: StreamClient):
        await client.ensure_stream("s1")
        off = await client.append("s1", EventType.USER_MESSAGE, {"text": "hello"})
        assert off == 0
        events = await client.read("s1")
        assert len(events) == 1
        assert events[0].type == EventType.USER_MESSAGE
        assert events[0].data == {"text": "hello"}

    async def test_read_all(self, client: StreamClient):
        await client.ensure_stream("s1")
        for i in range(5):
            await client.append("s1", EventType.TOKEN, {"i": i})
        events = await client.read_all("s1")
        assert len(events) == 5

    async def test_tail_catches_up_and_exits_on_close(self, client: StreamClient):
        await client.ensure_stream("s1")
        await client.append("s1", EventType.TOKEN, {"text": "a"})
        await client.append("s1", EventType.TOKEN, {"text": "b"})
        await client.close_stream("s1")

        events = []
        async for event in client.tail("s1"):
            events.append(event)
        assert len(events) == 2


# ═══ Session metadata ════════════════════════════════════════════════════════


class TestSessionMetadata:
    async def test_connect_migrates_session_stream_id(self, tmp_path: Path):
        db_path = tmp_path / ".taui" / "store.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sessions ("
            "session_id TEXT PRIMARY KEY, "
            "description TEXT NOT NULL DEFAULT '', "
            "mode TEXT NOT NULL DEFAULT 'normal', "
            "created_at REAL NOT NULL, "
            "last_active REAL NOT NULL, "
            "message_count INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO sessions(session_id, created_at, last_active) "
            "VALUES ('old', 1, 1)"
        )
        conn.commit()
        conn.close()

        store = Store(tmp_path)
        await store.connect()
        try:
            meta = await store.get_session("old")
            assert meta is not None
            assert meta["stream_id"] == ""
        finally:
            await store.close()

    async def test_create_session(self, store: Store):
        await store.create_session("ses-1")
        meta = await store.get_session("ses-1")
        assert meta is not None
        assert meta["session_id"] == "ses-1"
        assert meta["mode"] == "normal"
        assert meta["description"] == ""
        assert meta["message_count"] == 0

    async def test_create_session_with_stream_id(self, store: Store):
        await store.create_session("ses-1", stream_id="agents/ses-1")
        meta = await store.get_session("ses-1")
        assert meta["stream_id"] == "agents/ses-1"
        sessions = await store.list_sessions()
        assert sessions[0]["stream_id"] == "agents/ses-1"

    async def test_create_session_extensions(self, store: Store):
        await store.create_session("ses-2", mode="extensions")
        meta = await store.get_session("ses-2")
        assert meta["mode"] == "extensions"

    async def test_create_session_idempotent(self, store: Store):
        await store.create_session("ses-1")
        await store.create_session("ses-1")  # INSERT OR IGNORE
        meta = await store.get_session("ses-1")
        assert meta is not None

    async def test_update_session_description(self, store: Store):
        await store.create_session("ses-1")
        await store.update_session("ses-1", description="Hello world")
        meta = await store.get_session("ses-1")
        assert meta["description"] == "Hello world"

    async def test_update_session_message_count(self, store: Store):
        await store.create_session("ses-1")
        await store.update_session("ses-1", message_count=5)
        meta = await store.get_session("ses-1")
        assert meta["message_count"] == 5

    async def test_update_session_mode(self, store: Store):
        await store.create_session("ses-1")
        await store.update_session("ses-1", mode="extensions")
        meta = await store.get_session("ses-1")
        assert meta["mode"] == "extensions"

    async def test_list_sessions_empty(self, store: Store):
        sessions = await store.list_sessions()
        assert sessions == []

    async def test_list_sessions_ordered(self, store: Store):
        await store.create_session("ses-1")
        await store.create_session("ses-2")
        await store.update_session("ses-1")  # touch last_active
        sessions = await store.list_sessions()
        assert len(sessions) == 2
        # ses-1 should be first (updated most recently)
        assert sessions[0]["session_id"] == "ses-1"

    async def test_get_session_missing(self, store: Store):
        meta = await store.get_session("nope")
        assert meta is None

    async def test_list_sessions_limit(self, store: Store):
        for i in range(10):
            await store.create_session(f"ses-{i}")
        sessions = await store.list_sessions(limit=3)
        assert len(sessions) == 3

    async def test_tail_live_receives_new_data(
        self, client: StreamClient, store: Store
    ):
        await client.ensure_stream("s1")
        received: list[Event] = []

        async def consumer():
            async for event in client.tail("s1", poll_timeout=2.0):
                received.append(event)
                if len(received) >= 3:
                    break

        async def producer():
            await asyncio.sleep(0.05)
            for i in range(3):
                await client.append("s1", EventType.TOKEN, {"i": i})
                await asyncio.sleep(0.02)

        await asyncio.gather(
            asyncio.create_task(consumer()),
            asyncio.create_task(producer()),
        )
        assert len(received) == 3
        assert [e.data["i"] for e in received] == [0, 1, 2]


# ═══ EventType ════════════════════════════════════════════════════════════════


class TestEventType:
    def test_event_type_values(self):
        assert EventType.TOKEN.value == "token"
        assert EventType.TOOL_CALL.value == "tool_call"

    def test_event_type_from_string(self):
        assert EventType("token") == EventType.TOKEN

    def test_event_is_frozen(self):
        event = Event(
            stream_id="s1",
            offset=0,
            type=EventType.TOKEN,
            data={"text": "x"},
            created_at=0.0,
        )
        with pytest.raises(AttributeError):
            event.offset = 1  # type: ignore[misc]
