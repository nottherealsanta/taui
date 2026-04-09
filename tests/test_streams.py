"""
Tests for the taui.streams package — StreamStore, StreamClient, and HTTP server router.

Coverage:
- StreamStore: create, append, read, close, delete, idempotency, error handling, live-tail
- StreamClient: ensure_stream, append_auto, append_event, read, read_all, tail
- HTTP router: PUT/POST/GET/HEAD/DELETE endpoints, SSE live-tail, long-poll
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from taui.streams.store import (
    OffsetConflictError,
    StreamChunk,
    StreamClosedError,
    StreamNotFoundError,
    StreamStore,
)
from taui.streams.client import StreamClient

pytestmark = pytest.mark.anyio


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def store(tmp_path: Path) -> StreamStore:
    """Create a connected StreamStore backed by a temp directory."""
    s = StreamStore(tmp_path)
    await s.connect()
    yield s  # type: ignore[misc]
    await s.close()


@pytest.fixture
async def client(store: StreamStore) -> StreamClient:
    """Create a StreamClient wrapping the test store."""
    return StreamClient(store)


# ══════════════════════════════════════════════════════════════════════════════
# StreamStore tests
# ══════════════════════════════════════════════════════════════════════════════


class TestStreamStoreLifecycle:
    async def test_connect_creates_db(self, tmp_path: Path) -> None:
        store = StreamStore(tmp_path)
        await store.connect()
        assert store.db_path.exists()
        await store.close()

    async def test_double_connect_is_idempotent(self, store: StreamStore) -> None:
        # Should not raise
        await store.connect()

    async def test_double_close_is_idempotent(self, tmp_path: Path) -> None:
        store = StreamStore(tmp_path)
        await store.connect()
        await store.close()
        await store.close()  # Should not raise


class TestStreamStoreCRUD:
    async def test_create_stream(self, store: StreamStore) -> None:
        created = await store.create_stream("test/stream-1")
        assert created is True
        assert await store.stream_exists("test/stream-1")

    async def test_create_stream_idempotent(self, store: StreamStore) -> None:
        await store.create_stream("test/idem")
        created_again = await store.create_stream("test/idem")
        assert created_again is False

    async def test_stream_exists_false_for_missing(self, store: StreamStore) -> None:
        assert await store.stream_exists("nonexistent") is False

    async def test_get_stream_info(self, store: StreamStore) -> None:
        await store.create_stream("test/info")
        info = await store.get_stream_info("test/info")
        assert info is not None
        assert info["stream_id"] == "test/info"
        assert info["closed"] == 0
        assert info["length"] == 0

    async def test_get_stream_info_none_for_missing(self, store: StreamStore) -> None:
        info = await store.get_stream_info("missing")
        assert info is None

    async def test_delete_stream(self, store: StreamStore) -> None:
        await store.create_stream("test/delete-me")
        await store.append_auto("test/delete-me", b"data")
        deleted = await store.delete_stream("test/delete-me")
        assert deleted is True
        assert await store.stream_exists("test/delete-me") is False

    async def test_delete_nonexistent_returns_false(self, store: StreamStore) -> None:
        deleted = await store.delete_stream("nonexistent")
        assert deleted is False


class TestStreamStoreAppend:
    async def test_append_at_offset(self, store: StreamStore) -> None:
        await store.create_stream("test/append")
        offset = await store.append("test/append", offset=0, data=b"first")
        assert offset == 0

    async def test_append_auto(self, store: StreamStore) -> None:
        await store.create_stream("test/auto")
        o0 = await store.append_auto("test/auto", b"chunk-0")
        o1 = await store.append_auto("test/auto", b"chunk-1")
        o2 = await store.append_auto("test/auto", b"chunk-2")
        assert o0 == 0
        assert o1 == 1
        assert o2 == 2

    async def test_append_to_nonexistent_stream_raises(
        self, store: StreamStore
    ) -> None:
        with pytest.raises(StreamNotFoundError):
            await store.append("nonexistent", offset=0, data=b"data")

    async def test_append_auto_to_nonexistent_raises(self, store: StreamStore) -> None:
        with pytest.raises(StreamNotFoundError):
            await store.append_auto("nonexistent", b"data")

    async def test_append_to_closed_stream_raises(self, store: StreamStore) -> None:
        await store.create_stream("test/closed")
        await store.close_stream("test/closed")
        with pytest.raises(StreamClosedError):
            await store.append("test/closed", offset=0, data=b"data")

    async def test_append_auto_to_closed_stream_raises(
        self, store: StreamStore
    ) -> None:
        await store.create_stream("test/closed-auto")
        await store.close_stream("test/closed-auto")
        with pytest.raises(StreamClosedError):
            await store.append_auto("test/closed-auto", b"data")

    async def test_append_idempotent_same_data(self, store: StreamStore) -> None:
        await store.create_stream("test/idempotent")
        await store.append("test/idempotent", offset=0, data=b"same")
        # Same offset, same data — should succeed (idempotent)
        offset = await store.append("test/idempotent", offset=0, data=b"same")
        assert offset == 0

    async def test_append_offset_conflict_different_data(
        self, store: StreamStore
    ) -> None:
        await store.create_stream("test/conflict")
        await store.append("test/conflict", offset=0, data=b"original")
        with pytest.raises(OffsetConflictError):
            await store.append("test/conflict", offset=0, data=b"different")


class TestStreamStoreRead:
    async def test_read_empty_stream(self, store: StreamStore) -> None:
        await store.create_stream("test/empty")
        chunks = await store.read("test/empty")
        assert chunks == []

    async def test_read_returns_chunks_in_order(self, store: StreamStore) -> None:
        await store.create_stream("test/read")
        for i in range(5):
            await store.append_auto("test/read", f"chunk-{i}".encode())
        chunks = await store.read("test/read")
        assert len(chunks) == 5
        for i, chunk in enumerate(chunks):
            assert chunk.offset == i
            assert chunk.data == f"chunk-{i}".encode()
            assert chunk.stream_id == "test/read"

    async def test_read_from_offset(self, store: StreamStore) -> None:
        await store.create_stream("test/offset-read")
        for i in range(10):
            await store.append_auto("test/offset-read", f"c{i}".encode())
        chunks = await store.read("test/offset-read", from_offset=7)
        assert len(chunks) == 3
        assert chunks[0].offset == 7
        assert chunks[2].offset == 9

    async def test_read_with_limit(self, store: StreamStore) -> None:
        await store.create_stream("test/limited")
        for i in range(10):
            await store.append_auto("test/limited", f"c{i}".encode())
        chunks = await store.read("test/limited", limit=3)
        assert len(chunks) == 3

    async def test_read_nonexistent_stream_raises(self, store: StreamStore) -> None:
        with pytest.raises(StreamNotFoundError):
            await store.read("nonexistent")

    async def test_get_stream_length(self, store: StreamStore) -> None:
        await store.create_stream("test/length")
        assert await store.get_stream_length("test/length") == 0
        await store.append_auto("test/length", b"a")
        await store.append_auto("test/length", b"b")
        assert await store.get_stream_length("test/length") == 2


class TestStreamStoreClose:
    async def test_close_stream(self, store: StreamStore) -> None:
        await store.create_stream("test/closeable")
        await store.close_stream("test/closeable")
        assert await store.is_closed("test/closeable") is True

    async def test_close_nonexistent_raises(self, store: StreamStore) -> None:
        with pytest.raises(StreamNotFoundError):
            await store.close_stream("nonexistent")

    async def test_is_closed_on_open_stream(self, store: StreamStore) -> None:
        await store.create_stream("test/open")
        assert await store.is_closed("test/open") is False

    async def test_is_closed_on_nonexistent_raises(self, store: StreamStore) -> None:
        with pytest.raises(StreamNotFoundError):
            await store.is_closed("nonexistent")

    async def test_stream_info_after_close(self, store: StreamStore) -> None:
        await store.create_stream("test/close-info")
        await store.append_auto("test/close-info", b"event")
        await store.close_stream("test/close-info")
        info = await store.get_stream_info("test/close-info")
        assert info is not None
        assert info["closed"] == 1
        assert info["closed_at"] is not None
        assert info["length"] == 1


class TestStreamStoreLiveTail:
    async def test_wait_for_new_data_wakes_on_append(self, store: StreamStore) -> None:
        await store.create_stream("test/waiter")
        got_data = asyncio.Event()

        async def waiter():
            result = await store.wait_for_new_data("test/waiter", timeout=5.0)
            if result:
                got_data.set()

        task = asyncio.create_task(waiter())
        # Give the waiter a moment to start waiting
        await asyncio.sleep(0.05)
        await store.append_auto("test/waiter", b"wake-up")
        await asyncio.wait_for(got_data.wait(), timeout=2.0)
        assert got_data.is_set()
        await task

    async def test_wait_for_new_data_times_out(self, store: StreamStore) -> None:
        await store.create_stream("test/timeout")
        result = await store.wait_for_new_data("test/timeout", timeout=0.1)
        assert result is False

    async def test_close_wakes_waiters(self, store: StreamStore) -> None:
        await store.create_stream("test/close-wake")
        woke = asyncio.Event()

        async def waiter():
            result = await store.wait_for_new_data("test/close-wake", timeout=5.0)
            if result:
                woke.set()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        await store.close_stream("test/close-wake")
        await asyncio.wait_for(woke.wait(), timeout=2.0)
        assert woke.is_set()
        await task


# ══════════════════════════════════════════════════════════════════════════════
# StreamClient tests
# ══════════════════════════════════════════════════════════════════════════════


class TestStreamClient:
    async def test_ensure_stream_creates(
        self, client: StreamClient, store: StreamStore
    ) -> None:
        await client.ensure_stream("client/new")
        assert await store.stream_exists("client/new")

    async def test_ensure_stream_idempotent(self, client: StreamClient) -> None:
        await client.ensure_stream("client/idem")
        await client.ensure_stream("client/idem")  # No error

    async def test_close_stream(self, client: StreamClient, store: StreamStore) -> None:
        await client.ensure_stream("client/close")
        await client.close_stream("client/close")
        assert await store.is_closed("client/close") is True

    async def test_close_nonexistent_logs_warning(self, client: StreamClient) -> None:
        # Should not raise, just logs
        await client.close_stream("client/nonexistent")

    async def test_stream_exists(self, client: StreamClient) -> None:
        assert await client.stream_exists("nope") is False
        await client.ensure_stream("client/exists")
        assert await client.stream_exists("client/exists") is True

    async def test_get_stream_length(self, client: StreamClient) -> None:
        await client.ensure_stream("client/len")
        assert await client.get_stream_length("client/len") == 0
        await client.append_auto("client/len", b"a")
        assert await client.get_stream_length("client/len") == 1

    async def test_append_explicit_offset(self, client: StreamClient) -> None:
        await client.ensure_stream("client/explicit")
        offset = await client.append("client/explicit", offset=0, data=b"hello")
        assert offset == 0

    async def test_append_auto_with_dict(self, client: StreamClient) -> None:
        await client.ensure_stream("client/dict")
        offset = await client.append_auto("client/dict", {"key": "value"})
        assert offset == 0
        chunks = await client.read("client/dict")
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].data)
        assert parsed == {"key": "value"}

    async def test_append_auto_with_bytes(self, client: StreamClient) -> None:
        await client.ensure_stream("client/bytes")
        offset = await client.append_auto("client/bytes", b"raw-bytes")
        assert offset == 0
        chunks = await client.read("client/bytes")
        assert chunks[0].data == b"raw-bytes"

    async def test_append_event(self, client: StreamClient) -> None:
        await client.ensure_stream("client/event")
        offset = await client.append_event(
            "client/event", "state_change", {"state": "running"}
        )
        assert offset == 0
        chunks = await client.read("client/event")
        parsed = json.loads(chunks[0].data)
        assert parsed == {"type": "state_change", "state": "running"}

    async def test_read_from_offset(self, client: StreamClient) -> None:
        await client.ensure_stream("client/read-offset")
        for i in range(5):
            await client.append_auto("client/read-offset", {"n": i})
        chunks = await client.read("client/read-offset", from_offset=3)
        assert len(chunks) == 2
        assert json.loads(chunks[0].data)["n"] == 3

    async def test_read_all(self, client: StreamClient) -> None:
        await client.ensure_stream("client/read-all")
        for i in range(3):
            await client.append_auto("client/read-all", {"n": i})
        chunks = await client.read_all("client/read-all")
        assert len(chunks) == 3

    async def test_tail_catches_up_and_exits_on_close(
        self, client: StreamClient
    ) -> None:
        await client.ensure_stream("client/tail")
        # Pre-populate some data
        for i in range(3):
            await client.append_auto("client/tail", {"n": i})

        # Close the stream so tail exits after catch-up
        await client.close_stream("client/tail")

        collected: list[StreamChunk] = []
        async for chunk in client.tail("client/tail", from_offset=0, poll_timeout=1.0):
            collected.append(chunk)

        assert len(collected) == 3
        assert json.loads(collected[0].data)["n"] == 0
        assert json.loads(collected[2].data)["n"] == 2

    async def test_tail_resumes_from_offset(self, client: StreamClient) -> None:
        await client.ensure_stream("client/tail-resume")
        for i in range(5):
            await client.append_auto("client/tail-resume", {"n": i})
        await client.close_stream("client/tail-resume")

        collected: list[StreamChunk] = []
        async for chunk in client.tail(
            "client/tail-resume", from_offset=3, poll_timeout=1.0
        ):
            collected.append(chunk)

        assert len(collected) == 2
        assert json.loads(collected[0].data)["n"] == 3

    async def test_tail_live_receives_new_data(
        self, client: StreamClient, store: StreamStore
    ) -> None:
        await client.ensure_stream("client/tail-live")
        collected: list[StreamChunk] = []

        async def consumer():
            async for chunk in client.tail(
                "client/tail-live", from_offset=0, poll_timeout=2.0
            ):
                collected.append(chunk)
                if len(collected) >= 3:
                    break

        consumer_task = asyncio.create_task(consumer())

        # Give consumer a moment to start
        await asyncio.sleep(0.05)

        # Produce events
        for i in range(3):
            await client.append_auto("client/tail-live", {"n": i})
            await asyncio.sleep(0.01)

        await asyncio.wait_for(consumer_task, timeout=5.0)
        assert len(collected) == 3


# ══════════════════════════════════════════════════════════════════════════════
# HTTP server router tests
# ══════════════════════════════════════════════════════════════════════════════

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")


@pytest.fixture
def http_client(tmp_path: Path):
    """Create a FastAPI TestClient with a sync-managed StreamStore."""
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from taui.streams.server import create_streams_router

    loop = asyncio.new_event_loop()
    _store = StreamStore(tmp_path)
    loop.run_until_complete(_store.connect())

    app = FastAPI()
    router = create_streams_router(_store)
    app.include_router(router, prefix="/streams")

    with TestClient(app) as tc:
        yield tc

    loop.run_until_complete(_store.close())
    loop.close()


class TestStreamsHTTP:
    def test_put_creates_stream(self, http_client: Any) -> None:
        resp = http_client.put("/streams/test/http-create")
        assert resp.status_code == 201

    def test_put_idempotent(self, http_client: Any) -> None:
        http_client.put("/streams/test/idem-http")
        resp = http_client.put("/streams/test/idem-http")
        assert resp.status_code == 200

    def test_post_append(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-append")
        resp = http_client.post(
            "/streams/test/http-append",
            content=b'{"type":"event"}',
        )
        assert resp.status_code == 200
        assert resp.headers.get("Offset") == "0"

    def test_post_append_with_offset_header(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-offset")
        resp = http_client.post(
            "/streams/test/http-offset",
            content=b"first",
            headers={"Offset": "0"},
        )
        assert resp.status_code == 200
        assert resp.headers["Offset"] == "0"

    def test_post_to_nonexistent_returns_404(self, http_client: Any) -> None:
        resp = http_client.post(
            "/streams/nonexistent",
            content=b"data",
        )
        assert resp.status_code == 404

    def test_post_to_closed_returns_410(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-closed")
        http_client.delete("/streams/test/http-closed")
        resp = http_client.post(
            "/streams/test/http-closed",
            content=b"data",
        )
        assert resp.status_code == 410

    def test_post_offset_conflict_returns_409(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-conflict")
        http_client.post(
            "/streams/test/http-conflict",
            content=b"original",
            headers={"Offset": "0"},
        )
        resp = http_client.post(
            "/streams/test/http-conflict",
            content=b"different",
            headers={"Offset": "0"},
        )
        assert resp.status_code == 409

    def test_get_catchup_read(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-read")
        http_client.post("/streams/test/http-read", content=b'{"a":1}')
        http_client.post("/streams/test/http-read", content=b'{"a":2}')

        resp = http_client.get("/streams/test/http-read")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["offset"] == 0
        assert first["data"] == {"a": 1}

    def test_get_catchup_with_offset(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-offset-read")
        for i in range(5):
            http_client.post(
                "/streams/test/http-offset-read", content=json.dumps({"n": i}).encode()
            )

        resp = http_client.get("/streams/test/http-offset-read?offset=3")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["offset"] == 3

    def test_get_catchup_with_limit(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-limit")
        for i in range(10):
            http_client.post("/streams/test/http-limit", content=f"c{i}".encode())

        resp = http_client.get("/streams/test/http-limit?limit=3")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3

    def test_get_nonexistent_returns_404(self, http_client: Any) -> None:
        resp = http_client.get("/streams/nonexistent")
        assert resp.status_code == 404

    def test_get_stream_closed_header(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-closed-header")
        http_client.post("/streams/test/http-closed-header", content=b"data")
        http_client.delete("/streams/test/http-closed-header")

        resp = http_client.get("/streams/test/http-closed-header")
        assert resp.headers.get("Stream-Closed") == "true"

    def test_head_stream_info(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-head")
        http_client.post("/streams/test/http-head", content=b"chunk1")
        http_client.post("/streams/test/http-head", content=b"chunk2")

        resp = http_client.head("/streams/test/http-head")
        assert resp.status_code == 200
        assert resp.headers["Stream-Length"] == "2"
        assert resp.headers["Stream-Closed"] == "false"

    def test_head_nonexistent_returns_404(self, http_client: Any) -> None:
        resp = http_client.head("/streams/nonexistent")
        assert resp.status_code == 404

    def test_delete_closes_stream(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-delete")
        resp = http_client.delete("/streams/test/http-delete")
        assert resp.status_code == 200
        # Verify it's closed
        head_resp = http_client.head("/streams/test/http-delete")
        assert head_resp.headers["Stream-Closed"] == "true"

    def test_delete_nonexistent_returns_404(self, http_client: Any) -> None:
        resp = http_client.delete("/streams/nonexistent")
        assert resp.status_code == 404

    def test_catchup_stream_length_header(self, http_client: Any) -> None:
        http_client.put("/streams/test/http-len")
        for i in range(3):
            http_client.post("/streams/test/http-len", content=f"c{i}".encode())

        resp = http_client.get("/streams/test/http-len")
        assert resp.headers["Stream-Length"] == "3"

    def test_binary_data_round_trip(self, http_client: Any) -> None:
        """Non-JSON binary data should still be readable."""
        http_client.put("/streams/test/http-binary")
        http_client.post("/streams/test/http-binary", content=b"\x00\x01\x02\xff")
        resp = http_client.get("/streams/test/http-binary")
        assert resp.status_code == 200
        # Binary data gets decoded as replacement chars, but the round-trip works
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1
