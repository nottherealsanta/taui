"""Minimal FastAPI web server with WebSocket JSON-RPC bridge.

Single-client WebSocket, session-backed. Opt-in via ``--web``.
Requires: ``pip install fastapi uvicorn websockets``
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def create_app(
    workspace: Path | str | None = None,
    *,
    config: Any | None = None,
) -> Any:
    """Create a FastAPI application.

    Returns a FastAPI instance. Imports FastAPI at call time so the
    dependency is only required when ``--web`` is actually used.
    """
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    from taui.config import Config
    from taui.session import Session
    from .frontend import INDEX_HTML
    from .protocol import (
        JsonRpcProtocolError,
        error_message,
        parse_request,
        result_message,
        METHOD_NOT_FOUND,
        INTERNAL_ERROR,
    )

    resolved = Path(workspace).resolve() if workspace else Path.cwd()
    if config is None:
        config = Config.load(working_dir=resolved)

    # Shared mutable state — single client
    _session: Session | None = None
    _active_ws: WebSocket | None = None
    _lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal _session
        _session = await Session.create(config)
        logger.info("Web server started workspace=%s", resolved)
        try:
            yield
        finally:
            if _session:
                await _session.close()
            logger.info("Web server shut down")

    app = FastAPI(title="taui-server", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return INDEX_HTML

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        nonlocal _active_ws
        async with _lock:
            if _active_ws is not None:
                await websocket.accept()
                await websocket.close(code=1013, reason="single client only")
                return
            await websocket.accept()
            _active_ws = websocket

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    request = parse_request(raw)
                except JsonRpcProtocolError as exc:
                    await websocket.send_json(
                        error_message(exc.request_id, exc.code, exc.message, data=exc.data)
                    )
                    continue

                try:
                    rpc_result = await _dispatch(request.method, request.params)
                except JsonRpcProtocolError as exc:
                    if request.is_notification:
                        continue
                    await websocket.send_json(
                        error_message(request.request_id, exc.code, exc.message, data=exc.data)
                    )
                    continue
                except Exception as exc:
                    if request.is_notification:
                        continue
                    await websocket.send_json(
                        error_message(request.request_id, INTERNAL_ERROR, str(exc))
                    )
                    continue

                if not request.is_notification:
                    await websocket.send_json(
                        result_message(request.request_id, rpc_result)
                    )
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        finally:
            async with _lock:
                _active_ws = None

    async def _dispatch(method: str, params: dict[str, Any]) -> Any:
        assert _session is not None

        if method == "agent/send":
            message = params.get("message", "")
            if not message:
                raise JsonRpcProtocolError(
                    -32602, "Missing 'message' parameter"
                )
            started = time.perf_counter()
            result = await _session.send(message)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "text": result.text,
                "tool_uses": sum(tr.tool_calls_count for tr in result.turn_results),
                "turns": len(result.turn_results),
                "elapsed_ms": elapsed_ms,
            }
        elif method == "agent/status":
            return {
                "status": "ready",
                "session_id": _session.session_id,
                "extensions_mode": _session.extensions_mode,
            }
        elif method == "session/new":
            await _session.new_session()
            return {
                "session_id": _session.session_id,
                "mode": "extensions" if _session.extensions_mode else "normal",
            }
        elif method == "session/list":
            sessions = await _session.list_sessions()
            return {"sessions": sessions}
        elif method == "session/resume":
            sid = params.get("session_id", "")
            if not sid:
                raise JsonRpcProtocolError(
                    -32602, "Missing 'session_id' parameter"
                )
            ok = await _session.resume_session(sid)
            if not ok:
                raise JsonRpcProtocolError(-32602, f"Session not found: {sid}")
            return {
                "session_id": _session.session_id,
                "extensions_mode": _session.extensions_mode,
            }
        elif method == "session/toggleExtensions":
            is_on = await _session.toggle_extensions_mode()
            return {
                "extensions_mode": is_on,
                "session_id": _session.session_id,
            }
        elif method == "extensions/reload":
            loaded = _session.reload_extensions()
            return {"loaded": loaded}
        else:
            raise JsonRpcProtocolError(METHOD_NOT_FOUND, f"Unknown method: {method}")

    return app


def serve(
    workspace: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    config: Any | None = None,
) -> None:
    """Run the web server (blocking). Prints PORT:<n> when ready."""
    import socket
    import uvicorn

    app = create_app(workspace, config=config)

    if port == 0:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        port = sock.getsockname()[1]
    else:
        sock = None

    class _Server(uvicorn.Server):
        async def startup(self, sockets=None):  # type: ignore[override]
            await super().startup(sockets=sockets)
            if self.started:
                logger.info("taui web server on %s:%s", host, port)
                print(f"PORT:{port}", flush=True)

    uv_config = uvicorn.Config(
        app, host=host, port=port, log_level="warning", access_log=False,
    )
    server = _Server(uv_config)
    if sock:
        server.run(sockets=[sock])
        sock.close()
    else:
        server.run()
