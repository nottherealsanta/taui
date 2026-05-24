"""End-to-end test of the embedded MCP debug server.

Launches a real ``TauiApp`` in headless mode in a subprocess with the
debug server enabled, connects to its Unix socket, and exercises the
JSON-RPC tools (``screenshot``, ``get_state``, ``press_key``, etc.).

Run with::

    uv run python tests/test_debug_mcp.py
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
SOCK_PATH = Path(f"/tmp/taui-debug-test-{os.getpid()}.sock")


LAUNCHER = r"""
import logging, os, sys
logging.basicConfig(
    filename=os.environ.get("TAUI_TEST_LOG", "/tmp/taui-debug-test.log"),
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


class JsonRpcClient:
    """Tiny newline-delimited JSON-RPC client over a Unix socket."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id = 0

    async def connect(self) -> None:
        # Default StreamReader limit is 64 KiB; SVG screenshots easily exceed
        # that. Bump to 16 MiB so messages of any practical size pass through.
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
        assert self._writer is not None and self._reader is not None
        self._next_id += 1
        rid = self._next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self._writer.write((json.dumps(msg) + "\n").encode())
        await self._writer.drain()
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("Server closed connection")
            resp = json.loads(line)
            if resp.get("id") != rid:
                continue
            if "error" in resp:
                raise RuntimeError(
                    f"RPC error from {method}: {resp['error']}"
                )
            return resp["result"]


async def wait_for_socket(path: Path, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Socket {path} did not appear within {timeout}s")


def _print_step(label: str) -> None:
    print(f"\n=== {label} ===", flush=True)


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
    print(f"launched headless taui pid={proc.pid}, socket={SOCK_PATH}", flush=True)

    try:
        await wait_for_socket(SOCK_PATH)
    except TimeoutError:
        proc.kill()
        out, err = proc.communicate(timeout=5)
        print("STDOUT:", out.decode(errors="replace"))
        print("STDERR:", err.decode(errors="replace"))
        raise

    client = JsonRpcClient(SOCK_PATH)
    await client.connect()
    failures: list[str] = []

    try:
        # 1. initialize
        _print_step("initialize")
        init = await client.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0"},
            },
        )
        print(json.dumps(init, indent=2))
        assert init.get("serverInfo", {}).get("name") == "taui-debug", init

        # 2. tools/list
        _print_step("tools/list")
        tools = (await client.call("tools/list"))["tools"]
        names = sorted(t["name"] for t in tools)
        print("tools:", names)
        expected = {
            "send_message",
            "screenshot",
            "get_state",
            "get_messages",
            "press_key",
            "run_command",
            "query_widget",
            "wait_idle",
        }
        assert expected.issubset(set(names)), f"missing tools: {expected - set(names)}"

        # Give the session a moment to initialize (worker may need a beat)
        await asyncio.sleep(2.0)

        # 3. get_state — session + agent
        _print_step("get_state")
        state = (
            await client.call(
                "tools/call",
                {
                    "name": "get_state",
                    "arguments": {"include": ["session", "agent", "widgets"]},
                },
            )
        )["structuredContent"]
        print(json.dumps({k: v for k, v in state.items() if k != "widgets"}, indent=2))
        print(f"widgets: {len(state.get('widgets', []))} entries")
        # The chat-input widget should be present in the tree
        widget_ids = {w["id"] for w in state.get("widgets", [])}
        if "chat-input" not in widget_ids:
            failures.append("chat-input widget not found in widget tree")

        # 4. query_widget — chat-input
        _print_step("query_widget #chat-input")
        widget = (
            await client.call(
                "tools/call",
                {
                    "name": "query_widget",
                    "arguments": {"selector": "#chat-input", "property": "text"},
                },
            )
        )["structuredContent"]
        print(json.dumps(widget, indent=2))
        if widget.get("type") != "ChatInput":
            failures.append(f"unexpected chat-input widget type: {widget}")

        # 5. screenshot
        _print_step("screenshot")
        shot = (
            await client.call(
                "tools/call",
                {"name": "screenshot", "arguments": {"title": "debug-test"}},
            )
        )["structuredContent"]
        print(f"svg length: {shot.get('length')}")
        if not shot.get("content", "").startswith("<?xml") and "<svg" not in shot.get(
            "content", ""
        ):
            failures.append("screenshot did not return SVG content")
        # Save it so we can eyeball it
        (Path("/tmp") / "taui-debug-shot.svg").write_text(shot["content"])
        print("wrote /tmp/taui-debug-shot.svg")

        # 6. press_key — ctrl+b toggles sidebar
        _print_step("press_key ctrl+b (sidebar toggle)")
        res = (
            await client.call(
                "tools/call",
                {"name": "press_key", "arguments": {"key": "ctrl+b"}},
            )
        )["structuredContent"]
        print(json.dumps(res, indent=2))

        # 7. run_command /help — should not require a live LLM
        _print_step("run_command /help")
        res = (
            await client.call(
                "tools/call",
                {"name": "run_command", "arguments": {"command": "/help"}},
            )
        )["structuredContent"]
        print(json.dumps(res, indent=2))

        # 8. wait_idle
        _print_step("wait_idle")
        idle = (
            await client.call(
                "tools/call",
                {"name": "wait_idle", "arguments": {"timeout": 5.0}},
            )
        )["structuredContent"]
        print(json.dumps(idle, indent=2))

        # 9. get_messages after /help
        _print_step("get_messages last_n=5")
        msgs = (
            await client.call(
                "tools/call",
                {"name": "get_messages", "arguments": {"last_n": 5}},
            )
        )["structuredContent"]
        print(json.dumps(msgs, indent=2))

        # 10. ping
        _print_step("ping")
        pong = await client.call("ping")
        print(json.dumps(pong, indent=2))

    finally:
        await client.close()
        # Shut taui down
        proc.send_signal(signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
        if out:
            print("STDOUT:", out.decode(errors="replace")[-2000:])
        if err:
            print("STDERR:", err.decode(errors="replace")[-2000:])

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
