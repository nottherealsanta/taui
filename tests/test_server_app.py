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
                            "patch": {"markdown": "Core Updated"},
                        },
                    }
                )
            )

            update_resp = json.loads(ws.receive_text())
            assert update_resp["id"] == 3
            assert (
                update_resp["result"]["node"]["spec_ref"]
                == "specs/core.md#core-updated"
            )

            node_changed = json.loads(ws.receive_text())
            assert node_changed["method"] == "spec/nodeChanged"
            assert (
                node_changed["params"]["node"]["spec_ref"]
                == "specs/core.md#core-updated"
            )

            tree_changed = json.loads(ws.receive_text())
            assert tree_changed["method"] == "spec/treeChanged"
            assert tree_changed["params"]["previous_spec_ref"] == "specs/core.md#leaf"
            assert tree_changed["params"]["spec_ref"] == "specs/core.md#core-updated"


def test_get_node_code_refs_reads_workspace_files(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    src_root = tmp_path / "src"
    specs_root.mkdir(parents=True, exist_ok=True)
    src_root.mkdir(parents=True, exist_ok=True)

    (src_root / "worker.py").write_text(
        "\n".join(
            [
                "def run_task(name: str) -> str:",
                "    trimmed = name.strip()",
                "    if not trimmed:",
                "        raise ValueError('name is required')",
                "    return trimmed.upper()",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Spec root.",
                "",
                "    - {{tree: [Core](./core.md)}}",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    {{code\\_ref: `src/worker.py#L1-L3`}}",
                "    {{code\\_ref: `src/missing.py#L1-L2`}}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    app = create_app(workspace=tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/getNodeCodeRefs",
                        "params": {"spec_ref": "specs/core.md#core", "max_lines": 50},
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            refs = resp["result"]["refs"]

            assert len(refs) == 2
            assert refs[0]["file_path"] == "src/worker.py"
            assert refs[0]["preview_start"] == 1
            assert refs[0]["preview_end"] == 3
            assert "def run_task" in refs[0]["content"]
            assert refs[1]["file_path"] == "src/missing.py"
            assert refs[1]["error"] == "file not found"


def test_root_path_is_not_served(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 404


def test_get_tree_detailed_returns_nodes_with_content(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/getTreeDetailed",
                        "params": {},
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            assert resp["id"] == 1
            nodes = resp["result"]["nodes"]
            assert len(nodes) > 0
            # Every node must have a spec_ref and depth
            for node in nodes:
                assert "spec_ref" in node
                assert "depth" in node
                assert "markdown" in node


def test_create_sibling_node_inserts_and_notifies(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/createSiblingNode",
                        "params": {"spec_ref": "specs/core.md#leaf"},
                    }
                )
            )
            # First message: the RPC result
            result_msg = json.loads(ws.receive_text())
            assert result_msg["id"] == 1
            result = result_msg["result"]
            assert result["previous_spec_ref"] == "specs/core.md#leaf"
            assert result["tree_changed"] is True
            new_ref = result["node"]["spec_ref"]
            assert new_ref.startswith("specs/core.md#")

            # Next messages: treeChanged then nodeCreated notifications
            tree_changed = json.loads(ws.receive_text())
            assert tree_changed["method"] == "spec/treeChanged"
            assert tree_changed["params"]["previous_spec_ref"] == "specs/core.md#leaf"
            assert tree_changed["params"]["spec_ref"] == new_ref

            node_created = json.loads(ws.receive_text())
            assert node_created["method"] == "spec/nodeCreated"
            assert node_created["params"]["node"]["spec_ref"] == new_ref


def test_create_sibling_node_missing_spec_ref_returns_error(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/createSiblingNode",
                        "params": {},
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            assert resp["id"] == 1
            assert "error" in resp


def test_indent_node_makes_node_child_of_prev_sibling(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Root.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # Two siblings at level 2 so indent is possible
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core body.",
                "",
                "    - ## Alpha",
                "        Alpha body.",
                "",
                "    - ## Beta",
                "        Beta body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/indentNode",
                        "params": {"spec_ref": "specs/core.md#beta"},
                    }
                )
            )
            result_msg = json.loads(ws.receive_text())
            assert result_msg["id"] == 1
            result = result_msg["result"]
            assert result["previous_spec_ref"] == "specs/core.md#beta"
            assert result["tree_changed"] is True

            # Two notifications follow
            json.loads(ws.receive_text())  # treeChanged
            node_changed = json.loads(ws.receive_text())
            assert node_changed["method"] == "spec/nodeChanged"

            # Verify tree: beta should now appear under alpha
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
            nodes_by_ref = {n["spec_ref"]: n for n in tree_resp["result"]["nodes"]}
            assert (
                nodes_by_ref["specs/core.md#beta"]["depth"]
                > nodes_by_ref["specs/core.md#alpha"]["depth"]
            )


def test_indent_node_after_create_sibling_uses_correct_edge_order(
    tmp_path: Path,
) -> None:
    """Regression: createSiblingNode then indentNode must succeed.

    Before the fix, the new sibling's edge sort_order was set to len(siblings)
    (appended last) rather than anchor_edge_sort + 1 (inserted after anchor).
    get_children() orders by edge sort_order, so the new node appeared last
    and any previous sibling was the wrong node — or the node appeared at
    index 0, causing indent_node to reject with "no previous sibling".
    """
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Root.",
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
                "    Core body.",
                "",
                "    - ## Alpha",
                "        Alpha body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path)

    def rpc(ws, id_, method, params):
        ws.send_text(
            json.dumps(
                {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
            )
        )
        # Drain until we get the response for this id.
        while True:
            msg = json.loads(ws.receive_text())
            if msg.get("id") == id_:
                return msg
            # Notifications (no id) are discarded.

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # 1. Create a sibling after Alpha.
            create_resp = rpc(
                ws, 1, "spec/createSiblingNode", {"spec_ref": "specs/core.md#alpha"}
            )
            assert "error" not in create_resp, create_resp
            new_ref = create_resp["result"]["node"]["spec_ref"]

            # 2. Immediately indent the new sibling — it should become a child of Alpha.
            indent_resp = rpc(ws, 2, "spec/indentNode", {"spec_ref": new_ref})
            assert "error" not in indent_resp, indent_resp
            assert indent_resp["result"]["tree_changed"] is True

            # 3. Verify the new node is now deeper than Alpha.
            tree_resp = rpc(ws, 3, "spec/getTree", {})
            nodes_by_ref = {n["spec_ref"]: n for n in tree_resp["result"]["nodes"]}
            assert new_ref in nodes_by_ref, f"{new_ref!r} not in tree"
            assert (
                nodes_by_ref[new_ref]["depth"]
                > nodes_by_ref["specs/core.md#alpha"]["depth"]
            ), "new sibling should be a child of alpha after indent"


def test_indent_node_moves_children_with_parent(tmp_path: Path) -> None:
    """Regression: indenting a node must also increment depth of all descendants."""
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Root.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # Alpha → Beta (child of Alpha) → Gamma (child of Beta)
    # Charlie is a sibling of Alpha — pressing Tab on Alpha makes it child of Charlie.
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core body.",
                "",
                "    - ## Charlie",
                "        Charlie body.",
                "",
                "    - ## Alpha",
                "        Alpha body.",
                "",
                "        - ### Beta",
                "            Beta body.",
                "",
                "            - #### Gamma",
                "                Gamma body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path)

    def rpc(ws, id_, method, params):
        ws.send_text(
            json.dumps(
                {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
            )
        )
        while True:
            msg = json.loads(ws.receive_text())
            if msg.get("id") == id_:
                return msg

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Get baseline depths.
            tree0 = rpc(ws, 1, "spec/getTree", {})
            nodes0 = {n["spec_ref"]: n for n in tree0["result"]["nodes"]}
            alpha_depth0 = nodes0["specs/core.md#alpha"]["depth"]
            beta_depth0 = nodes0["specs/core.md#beta"]["depth"]
            gamma_depth0 = nodes0["specs/core.md#gamma"]["depth"]

            # Indent Alpha (makes it a child of Charlie).
            resp = rpc(ws, 2, "spec/indentNode", {"spec_ref": "specs/core.md#alpha"})
            assert "error" not in resp, resp

            # Verify all three nodes shifted by +1.
            tree1 = rpc(ws, 3, "spec/getTree", {})
            nodes1 = {n["spec_ref"]: n for n in tree1["result"]["nodes"]}
            assert nodes1["specs/core.md#alpha"]["depth"] == alpha_depth0 + 1, (
                "alpha depth +1"
            )
            assert nodes1["specs/core.md#beta"]["depth"] == beta_depth0 + 1, (
                "beta depth +1"
            )
            assert nodes1["specs/core.md#gamma"]["depth"] == gamma_depth0 + 1, (
                "gamma depth +1"
            )


def test_outdent_node_moves_children_with_parent(tmp_path: Path) -> None:
    """Regression: outdenting a node must also decrement depth of all descendants."""
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Root.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # Core → Alpha → Beta → Gamma
    # Outdenting Alpha makes it a sibling of Core; Beta and Gamma follow.
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core body.",
                "",
                "    - ## Alpha",
                "        Alpha body.",
                "",
                "        - ### Beta",
                "            Beta body.",
                "",
                "            - #### Gamma",
                "                Gamma body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path)

    def rpc(ws, id_, method, params):
        ws.send_text(
            json.dumps(
                {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
            )
        )
        while True:
            msg = json.loads(ws.receive_text())
            if msg.get("id") == id_:
                return msg

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Get baseline depths.
            tree0 = rpc(ws, 1, "spec/getTree", {})
            nodes0 = {n["spec_ref"]: n for n in tree0["result"]["nodes"]}
            alpha_depth0 = nodes0["specs/core.md#alpha"]["depth"]
            beta_depth0 = nodes0["specs/core.md#beta"]["depth"]
            gamma_depth0 = nodes0["specs/core.md#gamma"]["depth"]

            # Outdent Alpha (makes it a sibling of Core).
            resp = rpc(ws, 2, "spec/outdentNode", {"spec_ref": "specs/core.md#alpha"})
            assert "error" not in resp, resp

            # Verify all three nodes shifted by -1.
            tree1 = rpc(ws, 3, "spec/getTree", {})
            nodes1 = {n["spec_ref"]: n for n in tree1["result"]["nodes"]}
            assert nodes1["specs/core.md#alpha"]["depth"] == alpha_depth0 - 1, (
                "alpha depth -1"
            )
            assert nodes1["specs/core.md#beta"]["depth"] == beta_depth0 - 1, (
                "beta depth -1"
            )
            assert nodes1["specs/core.md#gamma"]["depth"] == gamma_depth0 - 1, (
                "gamma depth -1"
            )
            # Alpha's children must still be nested under Alpha (not under Core).
            assert (
                nodes1["specs/core.md#beta"]["depth"]
                > nodes1["specs/core.md#alpha"]["depth"]
            )
            assert (
                nodes1["specs/core.md#gamma"]["depth"]
                > nodes1["specs/core.md#beta"]["depth"]
            )


def test_outdent_node_raises_error_at_top_level(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # core.md#core is a level-1 heading — cannot outdent
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/outdentNode",
                        "params": {"spec_ref": "specs/core.md#core"},
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            assert resp["id"] == 1
            assert "error" in resp


def test_outdent_node_moves_up_one_level(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(["- Taui", "    Root.", "", "    - {{tree: [Core](./core.md)}}", ""]),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core body.",
                "",
                "    - ## Alpha",
                "        Alpha body.",
                "",
                "        - ### Deep",
                "            Deep body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/outdentNode",
                        "params": {"spec_ref": "specs/core.md#deep"},
                    }
                )
            )
            result_msg = json.loads(ws.receive_text())
            assert result_msg["id"] == 1
            result = result_msg["result"]
            assert result["previous_spec_ref"] == "specs/core.md#deep"
            assert result["tree_changed"] is True

            json.loads(ws.receive_text())  # treeChanged
            json.loads(ws.receive_text())  # nodeChanged

            # Verify: deep should now be at same level as alpha
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
            nodes_by_ref = {n["spec_ref"]: n for n in tree_resp["result"]["nodes"]}
            assert (
                nodes_by_ref["specs/core.md#deep"]["depth"]
                == nodes_by_ref["specs/core.md#alpha"]["depth"]
            )

    specs_root = tmp_path / "example_project" / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Example Project",
                "    Example intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace=tmp_path, specs_path="example_project/specs")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "spec/getTree",
                        "params": {},
                    }
                )
            )
            tree_resp = json.loads(ws.receive_text())
            nodes = tree_resp["result"]["nodes"]
            assert any(
                node["spec_ref"] == "example_project/specs/_main.md#example-project"
                for node in nodes
            )
