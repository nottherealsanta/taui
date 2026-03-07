from __future__ import annotations

from pathlib import Path

import pytest

from taui.specs import SpecNotFoundError, SpecService, SpecValidationError


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    (specs_root / "ui").mkdir(parents=True, exist_ok=True)

    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "Taui",
                "Agentic Coding Interface.",
                "",
                "- [Core](core.md#core)",
                "- [UI](ui/_main.md#taui-ui)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "# Core",
                "Core engine behaviors.{{status: ready}}",
                "",
                "## Leaf",
                "Leaf implementation details.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (specs_root / "ui" / "_main.md").write_text(
        "\n".join(
            [
                "# Taui UI",
                "Define the desktop interface contract.{{status: draft}}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_get_tree_indexes_recursive_links(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)
    refs = {node.spec_ref for node in service.get_tree()}
    assert "specs/_main.md#taui" in refs
    assert "specs/core.md#leaf" in refs


def test_update_node_title_and_intent(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    update = service.update_node(
        "specs/core.md#leaf",
        {"title": "Leaf Updated", "intent": "Updated leaf intent."},
    )

    assert update.previous_spec_ref == "specs/core.md#leaf"
    assert update.tree_changed is True
    assert update.node.spec_ref == "specs/core.md#leaf-updated"
    body = (tmp_path / "specs" / "core.md").read_text(encoding="utf-8")
    assert "## Leaf Updated" in body
    assert "Updated leaf intent." in body
    with pytest.raises(SpecNotFoundError):
        service.get_node("specs/core.md#leaf")


def test_update_content_rejects_non_leaf_section(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    with pytest.raises(SpecValidationError):
        service.update_node("specs/core.md#core", {"content": "new body"})


def test_update_plain_document_title(tmp_path: Path) -> None:
    _write_specs(tmp_path)
    service = SpecService(workspace=tmp_path)

    update = service.update_node("specs/_main.md#taui", {"title": "Taui Next"})

    assert update.node.spec_ref == "specs/_main.md#taui-next"
    main_content = (tmp_path / "specs" / "_main.md").read_text(encoding="utf-8")
    assert main_content.splitlines()[0] == "Taui Next"


def test_get_tree_includes_multiline_intent_text(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "Taui",
                "First intent line.",
                "Second intent line.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = service.get_tree()
    root = next(node for node in tree if node.spec_ref == "specs/_main.md#taui")
    assert root.intent == "First intent line.\nSecond intent line."


def test_get_tree_includes_multiline_paragraph_intent(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "Taui",
                "Primary line one.",
                "",
                "Primary line two.",
                "Primary line three.",
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
                "Core top line.",
                "",
                "Core second paragraph line.",
                "",
                "## Leaf",
                "Leaf line.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SpecService(workspace=tmp_path)
    tree = service.get_tree()
    root = next(node for node in tree if node.spec_ref == "specs/_main.md#taui")
    leaf = next(node for node in tree if node.spec_ref == "specs/core.md#leaf")
    assert root.intent == "Primary line one.\n\nPrimary line two.\nPrimary line three."
    assert leaf.intent == "Leaf line."
