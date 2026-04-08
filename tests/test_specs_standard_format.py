"""Tests for parsing specs in the new standard format (YAML frontmatter + markdown headings)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from taui.tangle import SpecService


def _run(coro):
    return asyncio.run(coro)


def _write_standard_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    (specs_root / "domains").mkdir(parents=True, exist_ok=True)
    (specs_root / "features").mkdir(parents=True, exist_ok=True)

    (specs_root / "main.md").write_text(
        "\n".join([
            "---",
            "title: Example Project",
            "status: active",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Project Spec",
            "",
            "## Purpose",
            "",
            "A simplified example project.",
            "",
        ]),
        encoding="utf-8",
    )

    (specs_root / "domains" / "task-management.md").write_text(
        "\n".join([
            "---",
            "title: Task Management",
            "status: active",
            "code_refs:",
            "  - src/task_board.py",
            "test_refs:",
            "  - tests/test_task_board.py",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Task Management",
            "",
            "## Responsibility",
            "",
            "Basic task tracking with boards and cards.",
            "",
        ]),
        encoding="utf-8",
    )

    (specs_root / "features" / "create-task.md").write_text(
        "\n".join([
            "---",
            "title: Create Task",
            "status: draft",
            "depends_on:",
            "  - specs/domains/task-management.md",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Create Task",
            "",
            "## Purpose",
            "",
            "Add new tasks to a board.",
            "",
        ]),
        encoding="utf-8",
    )


async def _get_tree(svc: SpecService) -> list:
    return await svc.get_tree()


def test_standard_format_get_tree_loads_nodes(tmp_path: Path) -> None:
    _write_standard_specs(tmp_path)
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    refs = {n.spec_ref for n in tree}
    # Root anchor from frontmatter title "Example Project" -> "example-project"
    assert any("main.md#example-project" in r for r in refs), refs
    assert any("task-management.md#task-management" in r for r in refs), refs
    assert any("create-task.md#create-task" in r for r in refs), refs


def test_standard_format_frontmatter_metadata_populates_node(tmp_path: Path) -> None:
    _write_standard_specs(tmp_path)
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    # Find the task-management root node
    tm_root = next(
        (n for n in tree if "task-management.md#task-management" in n.spec_ref),
        None,
    )
    assert tm_root is not None, f"task-management root not found in {[n.spec_ref for n in tree]}"
    assert tm_root.status == "active"
    # code_refs, test_refs, depends_on are no longer extracted from frontmatter;
    # they belong in the note body instead.
    assert tm_root.code_refs == []
    assert tm_root.verification is None


def test_standard_format_headings_create_child_nodes(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "main.md").write_text(
        "\n".join([
            "---",
            "title: My Doc",
            "status: active",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# My Doc",
            "",
            "## Section A",
            "",
            "Content A.",
            "",
            "## Section B",
            "",
            "Content B.",
            "",
            "### Sub-section",
            "",
            "Content Sub.",
            "",
        ]),
        encoding="utf-8",
    )
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    refs = {n.spec_ref for n in tree}
    # should have my-doc, section-a, section-b, sub-section
    assert any("main.md#my-doc" in r for r in refs), refs
    assert any("main.md#section-a" in r for r in refs), refs
    assert any("main.md#section-b" in r for r in refs), refs
    assert any("main.md#sub-section" in r for r in refs), refs


def test_standard_format_entry_point_is_main_md(tmp_path: Path) -> None:
    """main.md (not _main.md) is treated as the root entry point."""
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "main.md").write_text(
        "\n".join([
            "---",
            "title: Root Project",
            "status: active",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Root Project",
            "",
        ]),
        encoding="utf-8",
    )
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    assert len(tree) >= 1
    # root node should have depth=1
    root = next((n for n in tree if "main.md#root-project" in n.spec_ref), None)
    assert root is not None, f"root not found: {[n.spec_ref for n in tree]}"
    assert root.depth == 1


def test_standard_format_no_frontmatter_falls_back_to_legacy(tmp_path: Path) -> None:
    """A file without frontmatter is parsed via the legacy list-item path."""
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "- Legacy Node\n    Some legacy content.\n",
        encoding="utf-8",
    )
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    assert len(tree) >= 1
    assert any("legacy-node" in n.spec_ref for n in tree), [n.spec_ref for n in tree]


def test_standard_format_mixed_with_legacy(tmp_path: Path) -> None:
    """Both legacy (_main.md) and standard (domains/foo.md) in same specs/ work."""
    specs_root = tmp_path / "specs"
    (specs_root / "domains").mkdir(parents=True, exist_ok=True)

    (specs_root / "_main.md").write_text(
        "- Legacy Root\n    Legacy content.\n",
        encoding="utf-8",
    )
    (specs_root / "domains" / "foo.md").write_text(
        "\n".join([
            "---",
            "title: Foo Domain",
            "status: active",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Foo Domain",
            "",
            "Some content.",
            "",
        ]),
        encoding="utf-8",
    )
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    refs = {n.spec_ref for n in tree}
    assert any("legacy-root" in r for r in refs), refs
    assert any("foo.md#foo-domain" in r for r in refs), refs


def test_standard_format_slugify_from_frontmatter_title(tmp_path: Path) -> None:
    """Root node anchor comes from frontmatter title, child from heading text."""
    specs_root = tmp_path / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "main.md").write_text(
        "\n".join([
            "---",
            "title: My Feature",
            "status: active",
            "last_updated: 2026-03-20",
            "---",
            "",
            "# Purpose",
            "",
            "Do something useful.",
            "",
        ]),
        encoding="utf-8",
    )
    svc = SpecService(workspace=tmp_path, specs_path="specs")
    tree = _run(_get_tree(svc))
    refs = {n.spec_ref for n in tree}
    # Root anchor = slugify("My Feature") = "my-feature"
    assert any("main.md#my-feature" in r for r in refs), refs
    # Child anchor = slugify("Purpose") = "purpose"
    assert any("main.md#purpose" in r for r in refs), refs
