"""
RPC tests for Phase 2 agent endpoints via synchronous TestClient WebSocket.

These are plain synchronous tests (no anyio) to avoid event-loop conflicts
with the async tests in test_agent.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from taui.server.app import create_app


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Agentic Coding Interface.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core intent.",
                "",
                "    - ## Leaf",
                "        Leaf intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _rpc(ws: Any, id_: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    ws.send_text(
        json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    )
    while True:
        msg = json.loads(ws.receive_text())
        if msg.get("id") == id_:
            return msg


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_rpc_agent_launch_returns_agent_id(tmp_path: Path) -> None:
    """agent/launch RPC returns agent_id and session_id."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "agent/launch",
                {"spec_ref": "specs/core.md#core", "task": "Check the spec."},
            )
            assert "error" not in resp, resp
            assert "agent_id" in resp["result"]
            assert "session_id" in resp["result"]


def test_rpc_agent_list_returns_agents(tmp_path: Path) -> None:
    """agent/list returns a list (empty or with agents) after launch."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _rpc(
                ws,
                1,
                "agent/launch",
                {"spec_ref": "specs/core.md#core", "task": "List test."},
            )

            list_resp = _rpc(ws, 2, "agent/list", {})
            assert "error" not in list_resp, list_resp
            assert isinstance(list_resp["result"]["agents"], list)


def test_rpc_agent_launch_missing_spec_ref_returns_error(tmp_path: Path) -> None:
    """agent/launch with missing spec_ref returns INVALID_PARAMS error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "agent/launch", {"task": "No spec_ref."})
            assert "error" in resp


def test_rpc_agent_launch_missing_task_returns_error(tmp_path: Path) -> None:
    """agent/launch with missing task returns INVALID_PARAMS error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "agent/launch", {"spec_ref": "specs/core.md#core"})
            assert "error" in resp


def test_rpc_agent_stop_unknown_id_returns_error(tmp_path: Path) -> None:
    """agent/stop with an unknown agent_id returns an error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "agent/stop", {"agent_id": "does-not-exist"})
            assert "error" in resp


def test_rpc_initialize_advertises_agent_methods(tmp_path: Path) -> None:
    """initialize response includes agent/* methods in capabilities."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"workspace": str(tmp_path)},
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            methods = resp["result"]["capabilities"]["methods"]
            assert "agent/launch" in methods
            assert "agent/stop" in methods
            assert "agent/list" in methods
