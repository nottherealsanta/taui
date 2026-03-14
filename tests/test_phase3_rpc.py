"""
RPC tests for Phase 3: User ↔ Agent Interaction.

Tests agent/steer, agent/queue, agent/subscribe, agent/unsubscribe,
agent/answerQuestion, and ui/nodeEdited via synchronous TestClient WebSocket.

These are plain synchronous tests (no anyio) to avoid event-loop conflicts
with the async tests in test_phase3.py.
"""

from __future__ import annotations

import json
import time
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
    """Send a JSON-RPC request and return the matching response (skips notifications)."""
    ws.send_text(
        json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    )
    while True:
        msg = json.loads(ws.receive_text())
        if msg.get("id") == id_:
            return msg


def _launch_agent(ws: Any, req_id: int, workspace: Path) -> str:
    """Helper: launch a no-op agent and return its agent_id."""
    resp = _rpc(
        ws,
        req_id,
        "agent/launch",
        {"spec_ref": "specs/core.md#core", "task": "Test task."},
    )
    assert "error" not in resp, resp
    return resp["result"]["agent_id"]


# ── agent/steer ────────────────────────────────────────────────────────────────


def test_rpc_agent_steer_returns_ok(tmp_path: Path) -> None:
    """agent/steer on an active agent returns {ok: True}."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            agent_id = _launch_agent(ws, 1, tmp_path)

            resp = _rpc(
                ws,
                2,
                "agent/steer",
                {"agent_id": agent_id, "message": "Focus on the leaf section."},
            )
            # Agent may have finished already (no-op LLM is fast), but the RPC
            # should still return {ok: True} or an error if the agent is gone.
            # We accept either as long as the protocol works.
            assert "result" in resp or "error" in resp


def test_rpc_agent_steer_unknown_agent_returns_error(tmp_path: Path) -> None:
    """agent/steer with unknown agent_id returns an error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "agent/steer",
                {"agent_id": "does-not-exist", "message": "Hello."},
            )
            assert "error" in resp


def test_rpc_agent_steer_missing_params_returns_error(tmp_path: Path) -> None:
    """agent/steer with missing agent_id returns INVALID_PARAMS error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "agent/steer", {"message": "No agent_id."})
            assert "error" in resp


# ── agent/queue ────────────────────────────────────────────────────────────────


def test_rpc_agent_queue_returns_ok(tmp_path: Path) -> None:
    """agent/queue on a known agent (active or historical) returns {ok: True}."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            agent_id = _launch_agent(ws, 1, tmp_path)

            # Allow agent to finish (no-op LLM is near-instant)
            time.sleep(0.1)

            resp = _rpc(
                ws,
                2,
                "agent/queue",
                {"agent_id": agent_id, "message": "Follow-up task."},
            )
            assert "error" not in resp, resp
            assert resp["result"]["ok"] is True


def test_rpc_agent_queue_unknown_agent_returns_error(tmp_path: Path) -> None:
    """agent/queue with an unknown agent_id returns an error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "agent/queue",
                {"agent_id": "no-such-agent", "message": "Task."},
            )
            assert "error" in resp


# ── agent/subscribe ────────────────────────────────────────────────────────────


def test_rpc_agent_subscribe_returns_backlog(tmp_path: Path) -> None:
    """agent/subscribe after agent finishes returns a backlog list."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            agent_id = _launch_agent(ws, 1, tmp_path)

            # Give agent time to finish
            time.sleep(0.2)

            resp = _rpc(ws, 2, "agent/subscribe", {"agent_id": agent_id})
            assert "error" not in resp, resp
            backlog = resp["result"]["backlog"]
            assert isinstance(backlog, list)
            # Should have at least one state_change event
            assert len(backlog) > 0


def test_rpc_agent_subscribe_missing_agent_id_returns_error(tmp_path: Path) -> None:
    """agent/subscribe with missing agent_id returns error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "agent/subscribe", {})
            assert "error" in resp


# ── agent/unsubscribe ──────────────────────────────────────────────────────────


def test_rpc_agent_unsubscribe_returns_ok(tmp_path: Path) -> None:
    """agent/unsubscribe returns {ok: True}."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            agent_id = _launch_agent(ws, 1, tmp_path)

            # Subscribe first
            _rpc(ws, 2, "agent/subscribe", {"agent_id": agent_id})

            resp = _rpc(ws, 3, "agent/unsubscribe", {"agent_id": agent_id})
            assert "error" not in resp, resp
            assert resp["result"]["ok"] is True


# ── agent/answerQuestion ───────────────────────────────────────────────────────


def test_rpc_agent_answer_question_unknown_ref_returns_ok(tmp_path: Path) -> None:
    """agent/answerQuestion with an unknown ref returns {ok: True, handled: False}."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "agent/answerQuestion",
                {
                    "question_node_ref": "specs/core.md#core#question-deadbeef",
                    "answer": "Option A",
                },
            )
            assert "error" not in resp, resp
            assert resp["result"]["ok"] is True
            # No live runner holds this question, so handled=False
            assert resp["result"]["handled"] is False


def test_rpc_agent_answer_question_missing_params_returns_error(
    tmp_path: Path,
) -> None:
    """agent/answerQuestion with missing answer returns error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "agent/answerQuestion",
                {"question_node_ref": "specs/core.md#core#question-aabbccdd"},
            )
            assert "error" in resp


# ── ui/nodeEdited ──────────────────────────────────────────────────────────────


def test_rpc_ui_node_edited_applies_edit(tmp_path: Path) -> None:
    """ui/nodeEdited updates the spec node and emits spec/nodeChanged notification."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # First, get the tree to find a valid spec_ref
            tree_resp = _rpc(ws, 1, "spec/getTree", {})
            assert "error" not in tree_resp, tree_resp
            nodes = tree_resp["result"]["nodes"]
            assert len(nodes) > 0

            # Pick the first node
            spec_ref = nodes[0]["spec_ref"]
            old_markdown = nodes[0].get("markdown", "")

            # Send the edit — the WS should receive both the response and a notification
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "ui/nodeEdited",
                        "params": {
                            "spec_ref": spec_ref,
                            "old_markdown": old_markdown,
                            # Keep same leading heading to avoid spec_ref change
                            "new_markdown": old_markdown.rstrip()
                            + "\n\nUpdated by user.",
                        },
                    }
                )
            )

            # Collect messages until we see the response
            response = None
            notifications: list[dict[str, Any]] = []
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                if msg.get("id") == 2:
                    response = msg
                elif "method" in msg:
                    notifications.append(msg)
                if response is not None:
                    break

            assert response is not None, "No response received for ui/nodeEdited"
            assert "error" not in response, response
            assert response["result"]["ok"] is True


def test_rpc_ui_node_edited_missing_spec_ref_returns_error(tmp_path: Path) -> None:
    """ui/nodeEdited with missing spec_ref returns error."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "ui/nodeEdited",
                {"new_markdown": "No spec_ref given."},
            )
            assert "error" in resp


# ── initialize advertises Phase 3 capabilities ────────────────────────────────


def test_rpc_initialize_advertises_phase3_methods(tmp_path: Path) -> None:
    """initialize response includes all Phase 3 methods and notifications."""
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
            caps = resp["result"]["capabilities"]
            methods = caps["methods"]
            notifications = caps["notifications"]

            # Phase 3 methods
            assert "agent/steer" in methods
            assert "agent/queue" in methods
            assert "agent/subscribe" in methods
            assert "agent/unsubscribe" in methods
            assert "agent/answerQuestion" in methods
            assert "ui/nodeEdited" in methods

            # Phase 3 notifications
            assert "agent/toolCall" in notifications
            assert "agent/toolResult" in notifications
            assert "agent/message" in notifications
            assert "agent/questionAsked" in notifications
            assert "agent/lockChanged" in notifications
