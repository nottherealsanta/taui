# Web Server

FastAPI + WebSocket JSON-RPC server. Provides a browser-accessible interface to the agent session. Opt-in via `taui --web`.

---

## Architecture

```
taui --web
  │
  ├── Config.load()        → load provider/model/working_dir
  ├── create_app(config)   → FastAPI application factory
  │     │
  │     ├── Lifespan:
  │     │   ├── startup:  Session.create(config)
  │     │   └── shutdown: session.close()
  │     │
  │     ├── GET /healthz   → {"status": "ok"}
  │     │
  │     └── WS  /ws        → single-client JSON-RPC 2.0
  │           │
  │           ├── agent/send    → send message, return response
  │           └── agent/status  → return readiness
  │
  └── serve(workspace, config)  → uvicorn with auto port
```

---

## JSON-RPC 2.0 Protocol

The WebSocket endpoint speaks JSON-RPC 2.0. Each frame is a JSON object.

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "agent/send",
  "params": {"message": "What files are in src/?"}
}
```

### Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "text": "Here are the files...",
    "tool_uses": 2,
    "turns": 1,
    "elapsed_ms": 3200
  }
}
```

### Error Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {"code": -32601, "message": "Unknown method: foo/bar"}
}
```

### Notification (no `id`)

```json
{
  "jsonrpc": "2.0",
  "method": "notify",
  "params": {}
}
```

Notifications receive no response.

---

## RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `agent/send` | `message: str` | `{text, tool_uses, turns, elapsed_ms}` | Send a message to the agent |
| `agent/status` | — | `{status: "ready"}` | Health check |

---

## Error Codes

| Code | Constant | Meaning |
|------|----------|---------|
| -32700 | `PARSE_ERROR` | Invalid JSON |
| -32600 | `INVALID_REQUEST` | Not a valid JSON-RPC request |
| -32601 | `METHOD_NOT_FOUND` | Unknown method |
| -32602 | `INVALID_PARAMS` | Invalid method parameters |
| -32603 | `INTERNAL_ERROR` | Unhandled server exception |

---

## Single-Client Model

Only one WebSocket connection is active at a time. Additional connections receive a `1013` close code ("Try again later").

```python
async with self._lock:
    if self._active_ws is not None:
        await websocket.close(code=1013, reason="single client only")
        return
```

---

## Port Assignment

When `port=0` (default), the server binds to an OS-assigned free port and prints `PORT:<n>` to stdout once ready. This enables:

- Test harnesses to discover the port
- Frontend launchers to connect automatically

```
$ taui --web
PORT:54321
```

---

## Dependencies

The web server requires optional dependencies:

```
pip install fastapi uvicorn websockets
```

These are imported at call time — the rest of taui works without them.

---

## CLI Integration

```bash
taui --web                          # start web server (auto port)
taui --web -p codex -m o3-mini      # with provider/model overrides
taui --web -d /path/to/project      # explicit working directory
```

---

## Protocol Module

The protocol layer (`taui/server/protocol.py`) is standalone and can be used independently:

```python
from taui.server.protocol import parse_request, result_message, error_message

req = parse_request(raw_json_string)
# req.method, req.params, req.request_id, req.is_notification

response = result_message(req.request_id, {"ok": True})
err = error_message(req.request_id, -32601, "Unknown method")
```

---

## Module Layout

```
taui/server/
├── __init__.py     # public exports (protocol types)
├── app.py          # create_app() factory, serve() launcher
└── protocol.py     # JSON-RPC 2.0 parse/format helpers
```
