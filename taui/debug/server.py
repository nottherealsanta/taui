"""Embedded MCP JSON-RPC server for taui.

The server runs in a background thread inside the live taui process and
exposes a Unix domain socket. External clients connect via newline-
delimited JSON-RPC (the same protocol used by ``taui.mcp.McpClient``).

Methods exposed (MCP-style):

- ``initialize``       — handshake
- ``tools/list``       — list available debug tools
- ``tools/call``       — call a debug tool (``send_message``, etc.)

Each tool handler dispatches to ``taui.debug.tools``. Mutations of the
TUI cross the thread boundary via ``app.call_from_thread``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from taui.debug.tools import HANDLERS, TOOL_SCHEMAS

if TYPE_CHECKING:  # pragma: no cover
    from taui.tui.app import TauiApp

logger = logging.getLogger(__name__)


PROTOCOL_VERSION = "2024-11-05"


def default_socket_path(pid: int | None = None) -> Path:
    return Path("/tmp") / f"taui-debug-{pid or os.getpid()}.sock"


class DebugServer:
    """Background-thread JSON-RPC server bound to a Unix socket.

    Usage::

        server = DebugServer(app)
        server.start()  # non-blocking; prints socket path to stderr
        app.run()       # blocks
        server.stop()
    """

    def __init__(
        self,
        app: "TauiApp",
        *,
        socket_path: str | os.PathLike[str] | None = None,
        announce_to_stderr: bool = True,
    ) -> None:
        self._app = app
        self._socket_path = Path(socket_path) if socket_path else default_socket_path()
        self._announce = announce_to_stderr
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._ready = threading.Event()
        self._stop_event: asyncio.Event | None = None

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        # Clean up any stale socket file.
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
        except OSError:
            pass

        self._thread = threading.Thread(
            target=self._thread_main,
            name="taui-debug-server",
            daemon=True,
        )
        self._thread.start()
        # Wait for the server to bind before returning.
        self._ready.wait(timeout=5.0)

        if self._announce:
            print(
                f"[taui-debug] MCP server listening on {self._socket_path}",
                file=sys.stderr,
                flush=True,
            )

    def stop(self) -> None:
        if self._loop is None or self._stop_event is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        # Best-effort socket cleanup
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
        except OSError:
            pass

    # ── server thread ────────────────────────────────────────────────────

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("Debug server crashed")
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _serve(self) -> None:
        self._stop_event = asyncio.Event()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
            # Allow large argument payloads (e.g. base-64 images) on the
            # request side. Responses don't go through this limit.
            limit=16 * 1024 * 1024,
        )
        # Restrict permissions to the current user.
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError:
            pass
        self._ready.set()
        try:
            await self._stop_event.wait()
        finally:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername") or "?"
        logger.debug("debug client connected: %s", peer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    await self._write(
                        writer,
                        self._error_response(None, -32700, f"Parse error: {exc}"),
                    )
                    continue

                response = await self._dispatch(msg)
                if response is not None:
                    await self._write(writer, response)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            logger.exception("Error handling debug client")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _write(
        self, writer: asyncio.StreamWriter, payload: dict[str, Any]
    ) -> None:
        data = (json.dumps(payload) + "\n").encode()
        writer.write(data)
        await writer.drain()

    # ── dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications (no id) — no response.
        if req_id is None:
            logger.debug("notification: %s", method)
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "taui-debug",
                        "version": "0.1.0",
                    },
                }
            elif method == "tools/list":
                result = {"tools": TOOL_SCHEMAS}
            elif method == "tools/call":
                result = await self._call_tool(params)
            elif method == "ping":
                result = {}
            else:
                return self._error_response(
                    req_id, -32601, f"Method not found: {method}"
                )
        except Exception as exc:
            logger.exception("Dispatch error for %s", method)
            return self._error_response(req_id, -32000, str(exc))

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name!r}")

        # Tool handlers may block (call_from_thread, polling) — run in
        # executor so we don't stall the server loop.
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, handler, self._app, arguments)
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

        # MCP "tools/call" response shape: a list of content blocks plus
        # the structured payload. We embed JSON as text so both flavors
        # of client (text-only and structured) can read it.
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, default=str)}
            ],
            "structuredContent": result,
            "isError": False,
        }

    def _error_response(
        self, req_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


__all__ = ["DebugServer", "default_socket_path"]
