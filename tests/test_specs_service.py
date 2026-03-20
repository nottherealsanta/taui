from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taui.specs import SpecNotFoundError, SpecService


def _run(coro):
    return asyncio.run(coro)


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    (specs_root / "ui").mkdir(parents=True, exist_ok=True)

    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Agentic Coding Interface.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "    - {{tree: [Taui UI](./ui/_main.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core engine behaviors.",
                "    - {{status: ready}}",
                "",
                "    - ## Leaf",
                "        Leaf implementation details.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (specs_root / "ui" / "_main.md").write_text(
        "\n".join(
            [
                "- # Taui UI",
                "    Define the desktop interface contract.",
                "    - {{status: draft}}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_get_tree_indexes_recursive_links(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)
    refs = {node.spec_ref for node in _run(service.get_tree())}
    assert "specs/_main.md#taui" in refs
    assert "specs/core.md#leaf" in refs


def test_update_node_markdown_renames_anchor(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    update = _run(
        service.update_node(
            "specs/core.md#leaf",
            {"markdown": "Leaf Updated\nUpdated leaf intent."},
        )
    )
    _run(service.writer.flush())

    assert update.previous_spec_ref == "specs/core.md#leaf"
    assert update.tree_changed is True
    assert update.node.spec_ref == "specs/core.md#leaf-updated"
    body = (tmp_path / "specs" / "core.md").read_text(encoding="utf-8")
    assert "- Leaf Updated" in body
    assert "Updated leaf intent." in body
    with pytest.raises(SpecNotFoundError):
        _run(service.get_node("specs/core.md#leaf"))


def test_update_markdown_allows_parent_section(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    update = _run(service.update_node("specs/core.md#core", {"markdown": "new body"}))
    assert update.node.markdown == "new body"


def test_update_root_list_title(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    update = _run(service.update_node("specs/_main.md#taui", {"markdown": "Taui Next"}))
    _run(service.writer.flush())

    assert update.node.spec_ref == "specs/_main.md#taui-next"
    main_content = (tmp_path / "specs" / "_main.md").read_text(encoding="utf-8")
    assert main_content.splitlines()[0] == "- Taui Next"


def test_update_node_rejects_legacy_patch_fields(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    with pytest.raises(ValueError, match="unsupported patch fields"):
        _run(service.update_node("specs/core.md#leaf", {"title": "No longer valid"}))


def test_empty_markdown_uses_unique_untitled_anchors(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    first = _run(service.update_node("specs/core.md#core", {"markdown": ""}))
    second = _run(service.update_node("specs/core.md#leaf", {"markdown": ""}))

    assert first.node.spec_ref == "specs/core.md#untitled"
    assert second.node.spec_ref == "specs/core.md#untitled-1"


def test_get_tree_includes_multiline_markdown_text(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    First intent line.",
                "    Second intent line.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = _run(service.get_tree())
    root = next(node for node in tree if node.spec_ref == "specs/_main.md#taui")
    assert root.markdown == "Taui\nFirst intent line.\nSecond intent line."


def test_get_tree_includes_multiline_paragraph_markdown(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Primary line one.",
                "",
                "    Primary line two.",
                "    Primary line three.",
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
                "    Core top line.",
                "",
                "    Core second paragraph line.",
                "",
                "    - ## Leaf",
                "        Leaf line.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = _run(service.get_tree())
    root = next(node for node in tree if node.spec_ref == "specs/_main.md#taui")
    leaf = next(node for node in tree if node.spec_ref == "specs/core.md#leaf")
    assert (
        root.markdown
        == "Taui\nPrimary line one.\n\nPrimary line two.\nPrimary line three."
    )
    assert leaf.markdown == "## Leaf\nLeaf line."


def test_metadata_only_list_item_creates_node(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Root",
                "",
                "    - {{status: ready}}",
                "        {{verification: met}}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = _run(service.get_tree())

    refs = {node.spec_ref for node in tree}
    assert refs == {"specs/_main.md#root"}
    root = next(node for node in tree if node.spec_ref == "specs/_main.md#root")
    assert root.status == "ready"
    assert root.verification == "met"


def test_metadata_only_siblings_do_not_create_nodes(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Root",
                "",
                "    - {{status: ready}}",
                "    - {{status: ready}}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = _run(service.get_tree())
    refs = {node.spec_ref for node in tree}
    assert refs == {"specs/_main.md#root"}
    root = tree[0]
    assert root.status == "ready"


def test_get_tree_uses_custom_specs_path(tmp_path: Path) -> None:
    specs_root = tmp_path / "tests" / "example_project" / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "main.md").write_text(
        "\n".join(
            [
                "---",
                "title: Example Project",
                "type: project",
                "status: active",
                "owners:",
                "  - example-team",
                "last_updated: 2026-03-20",
                "---",
                "",
                "# Project Spec",
                "",
                "Example intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path, specs_path="tests/example_project/specs")
    refs = {node.spec_ref for node in _run(service.get_tree())}
    assert "tests/example_project/specs/main.md#example-project" in refs


def test_dev_mode_does_not_create_cache_file(tmp_path: Path) -> None:
    """When dev_mode=True, SpecService should not create a SQLite cache file."""
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path, dev_mode=True)

    # Initialize and load tree
    refs = {node.spec_ref for node in _run(service.get_tree())}
    assert "specs/_main.md#taui" in refs
    assert "specs/core.md#leaf" in refs

    # Close the service
    _run(service.writer.flush())
    _run(service.db.close())

    # Cache file should not exist when dev_mode=True
    assert not service.db.db_path.exists()


def test_dev_mode_still_builds_db_from_markdown(tmp_path: Path) -> None:
    """Even in dev_mode, the DB should be built from markdown files."""
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path, dev_mode=True)

    # Initialize and verify nodes are loaded from markdown
    tree = _run(service.get_tree())
    assert len(tree) > 0

    # Verify specific nodes exist
    refs = {node.spec_ref for node in tree}
    assert "specs/_main.md#taui" in refs
    assert "specs/core.md#core" in refs
    assert "specs/core.md#leaf" in refs
    assert "specs/ui/_main.md#taui-ui" in refs

    # Verify node details are correct
    core_node = next(node for node in tree if node.spec_ref == "specs/core.md#core")
    assert core_node.markdown == "# Core\nCore engine behaviors."
    assert core_node.status == "ready"


def test_legacy_inline_status_still_parses(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Root",
                "    - # Core {{status: in-progress}}",
                "        Body text.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = _run(service.get_tree())
    core_node = next(node for node in tree if node.spec_ref == "specs/_main.md#core")
    assert core_node.status == "in_progress"
