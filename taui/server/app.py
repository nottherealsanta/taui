from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .handlers import MethodHandlers
from .protocol import JsonRpcProtocolError, error_message, parse_request, result_message


class _ConnectionManager:
    def __init__(self) -> None:
        self._active: WebSocket | None = None
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if self._active is not None:
                await websocket.accept()
                await websocket.close(code=1013, reason="single client only")
                return False
            await websocket.accept()
            self._active = websocket
            return True

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._active is websocket:
                self._active = None


def _latest_static_mtime_ns(static_root: Path) -> int:
    latest = 0
    for root, _, files in os.walk(static_root):
        for name in files:
            path = Path(root) / name
            mtime = path.stat().st_mtime_ns
            if mtime > latest:
                latest = mtime
    return latest


def create_app(workspace: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="taui-server", version="0.1.0")
    handlers = MethodHandlers(workspace=workspace)
    manager = _ConnectionManager()
    static_root = Path(__file__).resolve().parent.parent / "static"

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        registered = await manager.register(websocket)
        if not registered:
            return

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
                    dispatch = await handlers.dispatch(request)
                except JsonRpcProtocolError as exc:
                    if request.is_notification:
                        continue
                    await websocket.send_json(
                        error_message(exc.request_id, exc.code, exc.message, data=exc.data)
                    )
                    continue

                if not request.is_notification:
                    response: dict[str, Any] = result_message(
                        request.request_id, dispatch.result
                    )
                    await websocket.send_json(response)

                for notification in dispatch.notifications:
                    await websocket.send_json(notification)
        except WebSocketDisconnect:
            pass
        finally:
            await manager.unregister(websocket)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_root / "index.html")

    @app.get("/__reload_token")
    async def reload_token() -> dict[str, int]:
        return {"token": _latest_static_mtime_ns(static_root)}

    app.mount("/static", StaticFiles(directory=static_root), name="static")

    return app
