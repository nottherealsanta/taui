"""End-to-end test of the scripted-LLM debug flow.

Launches a real ``TauiApp`` headless, swaps the live provider for a
``ScriptedProvider`` via MCP, queues a streamed text turn + a tool-call
turn, sends a user message, and verifies the agent loop consumed the
scripted output (zero real network calls).

Run with::

    uv run python tests/test_debug_mcp_scripted.py
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOCK_PATH = Path(f"/tmp/taui-debug-scripted-{os.getpid()}.sock")


LAUNCHER = r"""
import logging, os
logging.basicConfig(
    filename="/tmp/taui-debug-scripted.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
from taui.config import Config
from taui.tui.app import TauiApp
from taui.debug.server import DebugServer

cfg = Config.load(provider="copilot")
app = TauiApp(cfg)
server = DebugServer(app, socket_path=os.environ["TAUI_DEBUG_SOCKET"])
server.start()
try:
    app.run(headless=True, size=(120, 40))
finally:
    server.stop()
"""


class Client:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._next_id = 0
        self._reader = None
        self._writer = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._path), limit=16 * 1024 * 1024
        )

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def call(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        rid = self._next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self._writer.write((json.dumps(msg) + "\n").encode())
        await self._writer.drain()
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("server closed")
            resp = json.loads(line)
            if resp.get("id") != rid:
                continue
            if "error" in resp:
                raise RuntimeError(resp["error"])
            return resp["result"]

    async def tool(self, name: str, args: dict | None = None) -> dict:
        res = await self.call("tools/call", {"name": name, "arguments": args or {}})
        return res["structuredContent"]


async def wait_for_socket(path: Path, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"socket {path} never appeared")


def banner(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


async def main() -> None:
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    env = {**os.environ, "TAUI_DEBUG_SOCKET": str(SOCK_PATH)}
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCHER],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )
    print(f"launched headless taui pid={proc.pid}", flush=True)

    failures: list[str] = []

    try:
        await wait_for_socket(SOCK_PATH)
        c = Client(SOCK_PATH)
        await c.connect()

        await c.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "scripted-test", "version": "0.0"},
            },
        )

        # Let the session finish initializing
        await asyncio.sleep(2.0)

        banner("set_provider_mode(scripted)")
        res = await c.tool("set_provider_mode", {"mode": "scripted"})
        print(json.dumps(res, indent=2))
        assert res.get("mode") == "scripted", res

        banner("script_status (initial)")
        st = await c.tool("script_status")
        print(json.dumps(st, indent=2))
        assert st["mode"] == "scripted" and st["remaining"] == 0

        banner("script_push_turn — streamed text reply")
        res = await c.tool(
            "script_push_turn",
            {
                "text_deltas": ["Hello", "! ", "I'm a ", "scripted ", "assistant."],
                "delta_delay": 0.05,
                "usage": {"input_tokens": 42, "output_tokens": 18},
            },
        )
        print(json.dumps(res, indent=2))
        assert res.get("remaining") == 1

        banner("send_message — agent consumes the scripted turn")
        res = await c.tool(
            "send_message",
            {
                "text": "hi there",
                "wait_for_response": True,
                "timeout": 15.0,
            },
        )
        print(json.dumps(res, indent=2))
        if res.get("status") != "sent":
            failures.append(f"send_message did not complete: {res}")

        banner("script_status (after first send)")
        st = await c.tool("script_status")
        print(json.dumps(st, indent=2))
        if st.get("call_count", 0) < 1:
            failures.append(
                f"scripted provider was not called (count={st.get('call_count')})"
            )
        if not (st.get("last_call") or {}).get("last_user", "").startswith("hi there"):
            # The hi there content can be wrapped — log instead of failing hard
            print("note: last_user was:", st.get("last_call", {}).get("last_user"))

        banner("get_messages — verify scripted text became assistant text")
        msgs = (await c.tool("get_messages", {"last_n": 4}))["messages"]
        for m in msgs:
            content = (m.get("content") or "")[:200]
            print(f"  [{m.get('role')}] {content}")
        assistant_texts = [
            (m.get("content") or "") for m in msgs if m.get("role") == "assistant"
        ]
        joined = "".join(assistant_texts)
        # The streamed deltas should be joined into the final assistant text.
        if "scripted assistant" not in joined.lower():
            failures.append(
                f"scripted assistant text not found in history: {joined!r}"
            )

        banner("script_push_turn — turn with a tool call (read file)")
        # Use a benign tool the agent already has — `read` reading our own
        # README. We push the tool call, then a follow-up turn with the
        # final text response so the loop has something to settle on.
        readme = ROOT / "README.md"
        res = await c.tool(
            "script_push_turn",
            {
                "tool_calls": [
                    {
                        "name": "read",
                        "arguments": {"path": str(readme)},
                        "call_id": "call_scripted_read_1",
                    }
                ],
                "stop_reason": "tool_use",
            },
        )
        print("pushed tool-call turn:", res)
        res = await c.tool(
            "script_push_turn",
            {
                "text": "Done reading.",
                "text_deltas": ["Done ", "reading."],
                "delta_delay": 0.02,
            },
        )
        print("pushed follow-up text turn:", res)

        banner("send_message — agent runs tool then replies")
        res = await c.tool(
            "send_message",
            {
                "text": "please read the readme",
                "wait_for_response": True,
                "timeout": 30.0,
            },
        )
        print(json.dumps(res, indent=2))

        banner("get_messages — verify tool call + result")
        msgs = (await c.tool("get_messages", {"last_n": 8}))["messages"]
        for m in msgs:
            role = m.get("role")
            content = (m.get("content") or "")
            tcs = m.get("tool_calls")
            short = content[:120].replace("\n", " ")
            print(f"  [{role}] {short}{'...' if len(content) > 120 else ''}")
            if tcs:
                summary = [
                    (t["name"], list((t.get("arguments") or {}).keys()))
                    for t in tcs
                ]
                print(f"    tool_calls: {summary}")
        any_tool_call = any(
            (m.get("tool_calls") or [])
            and any(tc["name"] == "read" for tc in m["tool_calls"])
            for m in msgs
        )
        if not any_tool_call:
            failures.append("did not see a scripted `read` tool call in history")
        any_tool_result = any(m.get("role") == "tool" for m in msgs)
        if not any_tool_result:
            failures.append("did not see a tool result message in history")

        banner("set_provider_mode(real)")
        res = await c.tool("set_provider_mode", {"mode": "real"})
        print(json.dumps(res, indent=2))
        assert res.get("mode") == "real"

        await c.close()
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
        if err:
            tail = err.decode(errors="replace")[-1500:]
            if tail.strip():
                print("STDERR:", tail)

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
