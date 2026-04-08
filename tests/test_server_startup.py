from __future__ import annotations

import asyncio
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


REPO_ROOT = Path(__file__).resolve().parents[1]


def _readline_with_timeout(stream, timeout_sec: float) -> str | None:
    out: queue.Queue[str] = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            out.put(stream.readline())
        except Exception:
            out.put("")

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    try:
        return out.get(timeout=timeout_sec)
    except queue.Empty:
        return None


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "Taui",
                "Agentic Coding Interface.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_server_startup_prints_port_and_accepts_websocket(tmp_path: Path) -> None:
    websockets = pytest.importorskip("websockets")
    _write_specs(tmp_path)

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "taui.server",
            "serve",
            "--workspace",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert process.stdout is not None
        line = _readline_with_timeout(process.stdout, timeout_sec=10)
        assert line is not None, "server did not print startup line within timeout"
        line = line.strip()
        assert re.match(r"^PORT:\d+$", line), line
        port = int(line.split(":", 1)[1])

        async def _roundtrip() -> None:
            uri = f"ws://127.0.0.1:{port}/ws"
            async with websockets.connect(uri) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"workspace": str(tmp_path)},
                        }
                    )
                )
                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert response["id"] == 1
                assert response["result"]["protocolVersion"] == "1.0"

        asyncio.run(_roundtrip())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

