"""Unit tests for YAML frontmatter parsing."""
from __future__ import annotations

from taui.tangle.markdown import HeadingNode, parse_heading_tree, parse_yaml_frontmatter


def test_parse_frontmatter_basic() -> None:
    lines = ["---", "title: Foo", "status: active", "---", "", "# Body"]
    fm, body_start = parse_yaml_frontmatter(lines)
    assert fm == {"title": "Foo", "status": "active"}
    assert body_start == 4


def test_parse_frontmatter_with_lists() -> None:
    lines = [
        "---",
        "title: My Feature",
        "code_refs:",
        "  - src/foo.py",
        "  - src/bar.py",
        "depends_on:",
        "  - specs/domains/data-layer.md",
        "---",
        "",
        "# Body",
    ]
    fm, body_start = parse_yaml_frontmatter(lines)
    assert fm["title"] == "My Feature"
    assert fm["code_refs"] == ["src/foo.py", "src/bar.py"]
    assert fm["depends_on"] == ["specs/domains/data-layer.md"]
    assert body_start == 8


def test_parse_frontmatter_missing() -> None:
    lines = ["# Just a heading", "Some text"]
    fm, body_start = parse_yaml_frontmatter(lines)
    assert fm == {}
    assert body_start == 0


def test_parse_frontmatter_unclosed() -> None:
    lines = ["---", "title: Foo", "# No closing fence"]
    fm, body_start = parse_yaml_frontmatter(lines)
    assert fm == {}
    assert body_start == 0


def test_parse_frontmatter_empty_body() -> None:
    lines = ["---", "title: Bar", "---"]
    fm, body_start = parse_yaml_frontmatter(lines)
    assert fm["title"] == "Bar"
    assert body_start == 3


def test_parse_heading_tree_basic() -> None:
    lines = ["# A", "Body A", "## B", "Body B", "## C", "### D", "Body D"]
    nodes = parse_heading_tree(lines)
    assert len(nodes) == 4

    a, b, c, d = nodes
    assert a.title == "A"
    assert a.level == 1
    assert a.parent_index is None
    assert "Body A" in a.body_lines

    assert b.title == "B"
    assert b.level == 2
    assert b.parent_index == 0  # A

    assert c.title == "C"
    assert c.level == 2
    assert c.parent_index == 0  # A (not B — same level)

    assert d.title == "D"
    assert d.level == 3
    assert d.parent_index == 2  # C


def test_parse_heading_tree_single() -> None:
    lines = ["# Title", "", "Some body text."]
    nodes = parse_heading_tree(lines)
    assert len(nodes) == 1
    assert nodes[0].title == "Title"
    assert nodes[0].parent_index is None
    assert any("Some body text." in line for line in nodes[0].body_lines)


def test_parse_heading_tree_empty() -> None:
    lines = ["Just prose, no headings."]
    nodes = parse_heading_tree(lines)
    assert nodes == []


def test_parse_heading_tree_respects_start() -> None:
    lines = ["---", "title: Skip me", "---", "", "# Real Heading", "body"]
    nodes = parse_heading_tree(lines, start=4)
    assert len(nodes) == 1
    assert nodes[0].title == "Real Heading"


def test_parse_heading_tree_body_strips_trailing_blank() -> None:
    lines = ["# A", "body line", "", ""]
    nodes = parse_heading_tree(lines)
    assert len(nodes) == 1
    # Trailing blank lines stripped from body
    assert nodes[0].body_lines[-1].strip() != "" or len(nodes[0].body_lines) == 1
