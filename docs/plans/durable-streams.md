# Durable Streams Integration Plan

## Problem Statement

Taui's agent session system has several structural fragilities that become costly as sessions grow longer and more complex:

**Event delivery is fire-and-forget.** `AgentRunner._emit()` (`taui/agent/runner.py:351`) calls the notification callback synchronously. If the WebSocket connection is down when an event fires, that event is silently dropped. The client has no way to recover missed events after reconnecting.

**Event buffers don't survive restarts.** `AgentManager._event_buffers` (`taui/agent/manager.py:48`) is a plain in-memory dict. `startup_recovery()` (`taui/agent/manager.py:431`) reconstructs it from SQLite on startup, but any events that were queued *after* the last DB write are gone. The recovery path is inherently racy.

**In-flight conversation history is volatile.** `AgentRunner._messages` (`taui/agent/runner.py:215`) is a Python list. If the server crashes mid-turn, the messages accumulated during that turn are lost. SQLite persistence (`_persist_message`) is best-effort and asynchronous — there is a window of loss.

**No multi-client fan-out.** The single `_notification_callback` wired through `AgentManager.set_notification_callback()` (`taui/agent/manager.py:56`) delivers to exactly one WebSocket. A second browser window or a desktop + web client cannot watch the same agent session.

**Token streaming has no replayability.** `prime/token` notifications (emitted during LLM streaming) go directly over the WebSocket with no offset tracking. A reconnecting client can never recover in-progress token output.

---

## Solution Overview

Replace in-memory event buffering and single-subscriber WebSocket delivery with [Durable Streams](https://github.com/durable-streams/durable-streams) as the event backbone.

Durable Streams is an HTTP-based protocol for append-only, offset-addressed byte streams. Key properties that fit Taui's needs:

- **Offset-based resumability**: clients store their last-read offset and resume exactly from there after any disconnect
- **Live tailing**: SSE and long-poll modes for real-time consumption with no WebSocket required
- **CDN-friendly / standard HTTP**: works through any proxy, load balancer, or Tauri webview
- **Idempotent producers**: safe to retry appends with the same offset; no duplicate events
- **Stream forking**: one stream can feed multiple independent readers at different positions
- **Simple protocol**: PUT to create, POST to append, GET with `?offset=N` to read catch-up or live

Each agent run gets its own durable stream. The stream is the authoritative ordered log of events for that run. SQLite remains the store for structured session metadata (state, cost, tool records, questions). The event *log* moves to durable streams.

---

## Architecture Design

### Stream Identity

Every agent run is identified by a stream URL:

```
/streams/agents/{agent_id}
```

Sub-agents use the same scheme. PrimeAgent gets:

```
/streams/prime
```

Token streams (for in-progress LLM output) are a sub-stream:

```
/streams/agents/{agent_id}/tokens
/streams/prime/tokens
```

### Backend Changes

#### 1. Durable Streams HTTP Server

Mount a durable streams server (using the `@durable-streams/server` Node.js package or a Python implementation of the [Durable Streams Protocol](https://github.com/durable-streams/durable-streams/blob/main/PROTOCOL.md)) alongside the existing FastAPI app.

The simplest option for a greenfield project is to implement the protocol directly in FastAPI — it is five HTTP operations:

| Operation | HTTP |
|-----------|------|
| Create stream | `PUT /streams/{id}` |
| Append event | `POST /streams/{id}` with `Offset` header |
| Read catch-up | `GET /streams/{id}?offset=N` |
| Read live (SSE) | `GET /streams/{id}?offset=N&live=sse` |
| Read live (poll) | `GET /streams/{id}?offset=N&live=long-poll` |

Storage backend: SQLite table `stream_events(stream_id, offset, data BLOB, created_at)` with a unique index on `(stream_id, offset)`. This keeps the dependency surface small and consistent with the existing `aiosqlite` usage.

#### 2. Event Appending in AgentRunner

Replace `AgentRunner._emit()` + `_persist_event()` with a single `_append_to_stream()` call that:

1. Serializes the `AgentEvent` as newline-delimited JSON
2. POSTs to `/streams/agents/{agent_id}` with the current offset in the `Offset` header
3. Increments the in-memory offset counter

The existing `AgentManager._on_agent_event()` (`taui/agent/manager.py:311`) path still emits WebSocket notifications for clients that are actively connected (low-latency path). The stream append is the *durable* path.

```python
# taui/agent/runner.py — new method
async def _append_to_stream(self, event: AgentEvent) -> None:
    data = json.dumps({"type": event.event_type, **event.payload}).encode()
    await self._stream_client.append(
        stream_id=f"agents/{self.agent_id}",
        offset=self._stream_offset,
        data=data,
    )
    self._stream_offset += 1
```

The `_stream_offset` is initialized from the stream's current length when the agent starts (or 0 for a new stream). This makes appends idempotent and restartable.

#### 3. Event Buffers → Stream Reads

`AgentManager._event_buffers` (`taui/agent/manager.py:48`) and `subscribe()` (`taui/agent/manager.py:242`) are replaced by a stream read:

```python
# taui/agent/manager.py — new subscribe path
async def subscribe(self, agent_id: str, from_offset: int = 0) -> AsyncIterator[AgentEvent]:
    async for chunk in self._stream_client.read(
        stream_id=f"agents/{agent_id}",
        offset=from_offset,
        live="sse",
    ):
        yield AgentEvent.from_json(chunk)
```

The client passes its last-known offset on reconnect. No events are ever lost.

#### 4. Startup Recovery Simplification

`AgentManager.startup_recovery()` (`taui/agent/manager.py:431`) currently reconstructs in-memory event buffers from SQLite. With streams as the event store, this method only needs to:

1. Mark interrupted sessions as `stopped` in SQLite
2. Append a synthetic `state_change { state: "stopped", reason: "server_restart" }` event to each interrupted agent's stream

The buffer reconstruction loop (`taui/agent/manager.py:461–484`) is eliminated.

#### 5. PrimeAgent Token Streaming

PrimeAgent currently emits `prime/token` notifications one-by-one over the WebSocket during LLM streaming. These are replaced by appends to `/streams/prime/tokens`. The WebSocket notification remains for latency, but the stream provides the replay source.

A reconnecting client reads `/streams/prime/tokens?offset=<last_seen>&live=sse` to catch up on missed tokens instantly.

### Frontend Changes

#### 1. Stream Client

Add `@durable-streams/client` as a dependency:

```json
// app/package.json
"@durable-streams/client": "^0.x"
```

Create a `StreamService` in `app/src/lib/services/`:

```typescript
// app/src/lib/services/stream.ts
import { createClient } from "@durable-streams/client";

export const streamClient = createClient({ baseUrl: "http://localhost:PORT/streams" });

export async function* readAgentEvents(agentId: string, fromOffset = 0) {
  for await (const chunk of streamClient.read(`agents/${agentId}`, { offset: fromOffset, live: "sse" })) {
    yield JSON.parse(new TextDecoder().decode(chunk));
  }
}
```

#### 2. Offset Tracking in Svelte Stores

Each agent detail panel stores the last-consumed offset in its Svelte store. On unmount or disconnect, the offset is saved to `localStorage`. On remount or reconnect, the store resumes from the stored offset.

```typescript
// app/src/lib/stores/agentDetail.svelte.ts
let streamOffset = $state(0);

// On reconnect:
for await (const event of readAgentEvents(agentId, streamOffset)) {
  streamOffset++;
  applyEvent(event);
}
```

#### 3. WebSocket Notifications (unchanged for low-latency)

The existing WebSocket JSON-RPC path (`agent/stateChanged`, `agent/toolBrief`, `agent/subscribeEvent`) continues to work for clients that are connected. This provides low-latency updates. The stream is the *fallback and catch-up* source, not the primary real-time path.

This means **no breaking change to the existing WebSocket protocol**. Streams are additive.

### Optional: Yjs for Spec Collaboration

The [Yjs Durable Streams Protocol](https://github.com/durable-streams/durable-streams/blob/main/packages/y-durable-streams/YJS-PROTOCOL.md) extends this same infrastructure for real-time collaborative document editing.

Each spec document gets a stream:
```
/streams/specs/{spec_ref}
```

The `@durable-streams/y-durable-streams` client (`YjsProvider`) wraps a Yjs `Y.Doc` and syncs it via this stream. Changes from any editor (user or agent) are immediately available to all other editors. The server handles automatic compaction (snapshot merging) at 1MB thresholds.

This would allow Prime and root agents to collaboratively edit a spec node while the user watches changes appear live — a natural fit for Taui's spec-driven model.

Spec collaboration is not a prerequisite for the agent stream work and can be implemented independently.

---

## Key Integration Points

### Files to Create

| File | Purpose |
|------|---------|
| `taui/streams/client.py` | Python async client for appending to and reading from durable streams |
| `taui/streams/server.py` | FastAPI router implementing the Durable Streams HTTP protocol |
| `taui/streams/store.py` | SQLite-backed stream event store (`aiosqlite`) |
| `app/src/lib/services/stream.ts` | Frontend TypeScript stream client wrapper |

### Files to Modify

| File | Change |
|------|--------|
| `taui/agent/runner.py` | Add `_append_to_stream()`, `_stream_offset`; call from `_emit()` + `_persist_event()` |
| `taui/agent/manager.py` | Replace `_event_buffers` with stream reads in `subscribe()`; simplify `startup_recovery()` |
| `taui/agent/prime.py` | Append token events to `/streams/prime/tokens` during LLM streaming |
| `taui/server/app.py` | Mount the `streams` FastAPI router |
| `app/src/lib/stores/agentDetail.svelte.ts` | Add offset tracking and stream-based catch-up |
| `app/package.json` | Add `@durable-streams/client` |

---

## Dependencies to Add

### Python (pyproject.toml)

No new external packages required if we implement the Durable Streams protocol directly in FastAPI using `aiosqlite` (which is already a dependency). The protocol is simple enough that a self-contained implementation is preferable to adding a Node.js sidecar.

If a production-ready server is needed later, the [Caddy Durable Streams plugin](https://github.com/durable-streams/durable-streams/tree/main/packages/caddy) can front the streams endpoint with no Python changes.

### TypeScript (app/package.json)

```json
"@durable-streams/client": "^0.x"
```

Optionally, for Yjs spec collaboration:
```json
"@durable-streams/y-durable-streams": "^0.x",
"yjs": "^13.x"
```

---

## What This Unlocks

| Capability | Before | After |
|-----------|--------|-------|
| Missed events on disconnect | Lost | Replayed from offset |
| Server restart recovery | Manual reconstruction from SQLite | Stream read from stored offset |
| Multiple watchers per agent | Not possible | Any number of readers at independent offsets |
| In-progress token replay | Not possible | Read `/streams/prime/tokens?offset=N` |
| Spec collaboration | File-based, single writer | Yjs CRDT, multi-writer with conflict resolution |
| Audit log for agent runs | SQLite `agent_events` table | Append-only stream (immutable by design) |
