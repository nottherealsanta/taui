from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .handlers import MethodHandlers
from .protocol import JsonRpcProtocolError, error_message, parse_request, result_message

logger = logging.getLogger(__name__)


class _ConnectionManager:
    def __init__(self) -> None:
        self._active: WebSocket | None = None
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if self._active is not None:
                logger.warning(
                    "Rejecting websocket connection: single client limit hit"
                )
                await websocket.accept()
                await websocket.close(code=1013, reason="single client only")
                return False
            await websocket.accept()
            self._active = websocket
            logger.info("Websocket client registered")
            return True

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._active is websocket:
                self._active = None
                logger.info("Websocket client unregistered")


def create_app(
    workspace: Path | str | None = None,
    specs_path: Path | str | None = None,
    dev_mode: bool = False,
) -> FastAPI:
    handlers = MethodHandlers(
        workspace=workspace, specs_path=specs_path, dev_mode=dev_mode
    )
    logger.info(
        "Creating FastAPI app workspace=%s",
        workspace or Path.cwd(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        started = time.perf_counter()
        logger.info("Application startup: initializing spec service")
        await handlers.specs.ensure_initialized()
        await handlers.history_db.connect()
        logger.info(
            "Application startup: running persistence recovery",
        )
        await handlers.agent_manager.startup_recovery()
        logger.info(
            "Application startup complete init_ms=%s",
            int((time.perf_counter() - started) * 1000),
        )
        try:
            yield
        finally:
            shutdown_started = time.perf_counter()
            logger.info(
                "Application shutdown: stopping agents, flushing writer and closing DB"
            )
            await handlers.agent_manager.shutdown()
            await handlers.specs.writer.flush()
            await handlers.specs.db.close()
            await handlers.history_db.close()
            logger.info(
                "Application shutdown complete duration_ms=%s",
                int((time.perf_counter() - shutdown_started) * 1000),
            )

    app = FastAPI(title="taui-server", version="0.1.0", lifespan=lifespan)
    manager = _ConnectionManager()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        registered = await manager.register(websocket)
        if not registered:
            return

        def send_notification(notification: dict[str, Any]) -> None:
            asyncio.create_task(websocket.send_json(notification))

        handlers.set_notification_callback(send_notification)

        try:
            while True:
                raw = await websocket.receive_text()
                logger.debug("RPC frame received bytes=%s", len(raw))
                try:
                    request = parse_request(raw)
                except JsonRpcProtocolError as exc:
                    logger.warning(
                        "RPC parse error code=%s message=%s", exc.code, exc.message
                    )
                    await websocket.send_json(
                        error_message(
                            exc.request_id, exc.code, exc.message, data=exc.data
                        )
                    )
                    continue

                try:
                    started = time.perf_counter()
                    dispatch = await handlers.dispatch(request)
                    await handlers.drain_notifications()
                    logger.debug(
                        "RPC dispatch complete method=%s request_id=%s duration_ms=%s notifications=%s",
                        request.method,
                        request.request_id,
                        int((time.perf_counter() - started) * 1000),
                        len(dispatch.notifications),
                    )
                except JsonRpcProtocolError as exc:
                    if request.is_notification:
                        logger.warning(
                            "Notification handling error method=%s code=%s message=%s",
                            request.method,
                            exc.code,
                            exc.message,
                        )
                        continue
                    logger.warning(
                        "RPC error response method=%s request_id=%s code=%s message=%s",
                        request.method,
                        request.request_id,
                        exc.code,
                        exc.message,
                    )
                    await websocket.send_json(
                        error_message(
                            exc.request_id, exc.code, exc.message, data=exc.data
                        )
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
            logger.info("Websocket disconnected")
        finally:
            handlers.set_notification_callback(None)
            await manager.unregister(websocket)

    return app
