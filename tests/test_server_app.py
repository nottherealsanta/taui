from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from taui.server.app import create_app


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "Taui",
                "Agentic Coding Interface.",
                "",
                "- [Core](core.md#core)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "# Core",
                "Core intent.",
                "",
                "## Leaf",
                "Leaf intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_websocket_roundtrip_and_spec_update_notifications(tmp_path: Path) -> None:
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
            init_resp = json.loads(ws.receive_text())
            assert init_resp["id"] == 1
            assert init_resp["result"]["protocolVersion"] == "1.0"

            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "spec/getTree",
                        "params": {},
                    }
                )
            )
            tree_resp = json.loads(ws.receive_text())
            nodes = tree_resp["result"]["nodes"]
            assert any(node["spec_ref"] == "specs/core.md#leaf" for node in nodes)

            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "spec/updateNode",
                        "params": {
                            "spec_ref": "specs/core.md#leaf",
                            "patch": {"title": "Core Updated"},
                        },
                    }
                )
            )

            update_resp = json.loads(ws.receive_text())
            assert update_resp["id"] == 3
            assert (
                update_resp["result"]["node"]["spec_ref"] == "specs/core.md#core-updated"
            )

            node_changed = json.loads(ws.receive_text())
            assert node_changed["method"] == "spec/nodeChanged"
            assert (
                node_changed["params"]["node"]["spec_ref"] == "specs/core.md#core-updated"
            )

            tree_changed = json.loads(ws.receive_text())
            assert tree_changed["method"] == "spec/treeChanged"
            assert (
                tree_changed["params"]["previous_spec_ref"] == "specs/core.md#leaf"
            )
            assert tree_changed["params"]["spec_ref"] == "specs/core.md#core-updated"


def test_static_root_serves_web_ui(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<div id=\"spec-tree\" class=\"tree\"></div>" in response.text


def test_reload_token_endpoint(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        response = client.get("/__reload_token")
        assert response.status_code == 200
        payload = response.json()
        assert "token" in payload
        assert isinstance(payload["token"], int)
