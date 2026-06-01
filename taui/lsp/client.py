"""Thin async LSP client over subprocess stdio."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_HEADER_SEP = b"\r\n\r\n"


class LspClient:
    """Manages a single LSP server subprocess over stdio JSON-RPC."""

    def __init__(self, cmd: list[str], *, cwd: str | None = None) -> None:
        self._cmd = cmd
        self._cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._initialized = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, root_uri: str) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        init_result = await self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": root_uri,
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "hover": {"contentFormat": ["plaintext", "markdown"]},
                        "documentSymbol": {"dynamicRegistration": False},
                        "implementation": {"dynamicRegistration": False},
                        "callHierarchy": {"dynamicRegistration": False},
                        "publishDiagnostics": {"relatedInformation": True},
                    },
                    "workspace": {
                        "symbol": {"dynamicRegistration": False},
                    },
                },
            },
        )
        await self.notify("initialized", {})
        self._initialized = True
        capabilities = list((init_result or {}).get("capabilities", {}).keys())
        log.info("LSP server started: %s  caps=%s", self._cmd, capabilities)

    async def stop(self) -> None:
        if not self._proc:
            return
        try:
            await self.request("shutdown", None, timeout=2.0)
            await self.notify("exit", None)
        except Exception:
            pass
        try:
            self._proc.terminate()
            await asyncio.wait_for(self._proc.wait(), timeout=1.0)
        except Exception:
            self._proc.kill()
        if self._reader_task:
            self._reader_task.cancel()
        self._proc = None
        self._initialized = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    # ------------------------------------------------------------------
    # json-rpc
    # ------------------------------------------------------------------

    async def request(
        self, method: str, params: Any, *, timeout: float = 30.0
    ) -> Any:
        self._req_id += 1
        rid = self._req_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._send(msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            self._pending.pop(rid, None)
            raise

    async def notify(self, method: str, params: Any) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send(msg)

    def _send(self, msg: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        body = json.dumps(msg).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self._proc.stdin.write(header + body)

    # ------------------------------------------------------------------
    # reader loop
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        reader = self._proc.stdout
        buf = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                while _HEADER_SEP in buf:
                    header_end = buf.index(_HEADER_SEP)
                    header_block = buf[:header_end].decode("ascii")
                    content_length = 0
                    for line in header_block.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())
                    body_start = header_end + len(_HEADER_SEP)
                    if len(buf) < body_start + content_length:
                        break  # wait for more data
                    body = buf[body_start : body_start + content_length]
                    buf = buf[body_start + content_length :]
                    self._handle_message(json.loads(body))
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("LSP reader loop error")

    def _handle_message(self, msg: dict[str, Any]) -> None:
        if "id" in msg and "method" not in msg:
            # response
            rid = msg["id"]
            fut = self._pending.pop(rid, None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(
                        LspError(msg["error"].get("message", "unknown error"))
                    )
                else:
                    fut.set_result(msg.get("result"))
        # notifications and server-initiated requests are ignored for now


class LspError(Exception):
    pass
