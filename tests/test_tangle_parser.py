from taui.tangle.parser import parse_tangle_document


BASIC_CONTENT = """---
title: Auth
last_updated: 2026-04-07
---

# Auth

Use -> src/auth.py:register_handler.
See [Data Layer](tangles/domains/data-layer.md).
Also tangles/domains/data-layer.md#behavior.
"""


def test_parse_tangle_document_extracts_frontmatter_refs_links() -> None:
    detail = parse_tangle_document("tangles/domains/auth.md", BASIC_CONTENT)
    assert detail.file.title == "Auth"
    assert detail.file.last_updated == "2026-04-07"
    assert len(detail.nodes) == 1
    assert len(detail.refs) == 1
    assert detail.refs[0].file_path == "src/auth.py"
    assert len(detail.links) >= 2


def test_parse_tangle_document_title_from_frontmatter() -> None:
    content = "---\ntitle: User Registration\nlast_updated: 2026-01-01\n---\n\n# User Registration\n\nHello.\n"
    detail = parse_tangle_document("tangles/features/user-registration.md", content)
    assert detail.file.title == "User Registration"
    assert detail.file.last_updated == "2026-01-01"


def test_parse_tangle_document_title_fallback_from_filename() -> None:
    content = "# Some Heading\n\nContent.\n"
    detail = parse_tangle_document("tangles/my-feature.md", content)
    assert detail.file.title == "My Feature"


def test_parse_tangle_document_multiple_headings_create_nodes() -> None:
    content = "---\ntitle: Spec\nlast_updated: 2026-04-07\n---\n\n# Overview\n\nIntro.\n\n## Behavior\n\nDetails.\n\n## Constraints\n\nLimits.\n"
    detail = parse_tangle_document("tangles/spec.md", content)
    assert len(detail.nodes) == 3
    headings = [n.heading for n in detail.nodes]
    assert "Overview" in headings
    assert "Behavior" in headings
    assert "Constraints" in headings


def test_parse_tangle_document_no_frontmatter() -> None:
    content = "# Just a heading\n\nSome prose.\n"
    detail = parse_tangle_document("tangles/simple.md", content)
    assert detail.frontmatter == {}
    assert len(detail.nodes) == 1
    assert detail.nodes[0].heading == "Just a heading"


def test_parse_tangle_document_extracts_multiple_refs() -> None:
    content = "---\ntitle: Multi\nlast_updated: 2026-04-07\n---\n\n# Multi\n\nSee -> src/auth.py:register_handler and `src/db.py:45-52`.\n"
    detail = parse_tangle_document("tangles/multi.md", content)
    assert len(detail.refs) == 2
    file_paths = {r.file_path for r in detail.refs}
    assert "src/auth.py" in file_paths
    assert "src/db.py" in file_paths


def test_parse_tangle_document_extracts_markdown_links() -> None:
    content = "---\ntitle: Linked\nlast_updated: 2026-04-07\n---\n\n# Linked\n\nSee [Auth](tangles/auth.md).\n"
    detail = parse_tangle_document("tangles/linked.md", content)
    assert any(lnk.target_path == "tangles/auth.md" for lnk in detail.links)
    assert all(
        lnk.link_type == "markdown_link"
        for lnk in detail.links
        if lnk.target_path == "tangles/auth.md"
    )


def test_parse_tangle_document_extracts_bare_tangle_links() -> None:
    content = "---\ntitle: Bare\nlast_updated: 2026-04-07\n---\n\n# Bare\n\nSee tangles/domains/data-layer.md#behavior.\n"
    detail = parse_tangle_document("tangles/bare.md", content)
    assert any("data-layer.md" in lnk.target_path for lnk in detail.links)


def test_parse_tangle_document_node_ids_are_stable() -> None:
    content = "---\ntitle: T\nlast_updated: 2026-04-07\n---\n\n# My Section\n\nBody.\n"
    detail = parse_tangle_document("tangles/t.md", content)
    assert len(detail.nodes) == 1
    assert detail.nodes[0].id == "tangles/t.md#my-section"
    assert detail.nodes[0].anchor == "my-section"


def test_parse_tangle_document_node_depth() -> None:
    content = "---\ntitle: D\nlast_updated: 2026-04-07\n---\n\n# Top\n\nA.\n\n## Sub\n\nB.\n\n### Deep\n\nC.\n"
    detail = parse_tangle_document("tangles/d.md", content)
    depths = {n.heading: n.depth for n in detail.nodes}
    assert depths["Top"] == 0
    assert depths["Sub"] == 1
    assert depths["Deep"] == 2


def test_parse_tangle_document_ref_line_numbers() -> None:
    content = "---\ntitle: Lines\nlast_updated: 2026-04-07\n---\n\n# Section\n\nFirst line.\nUse -> src/foo.py:bar here.\n"
    detail = parse_tangle_document("tangles/lines.md", content)
    assert len(detail.refs) == 1
    assert detail.refs[0].line_in_tangle > 0


def test_parse_tangle_document_frontmatter_passthrough() -> None:
    content = "---\ntitle: Custom\nlast_updated: 2026-04-07\ncustom_field: hello\n---\n\n# Custom\n\nBody.\n"
    detail = parse_tangle_document("tangles/custom.md", content)
    assert detail.frontmatter.get("custom_field") == "hello"


def test_parse_tangle_document_empty_document() -> None:
    detail = parse_tangle_document("tangles/empty.md", "")
    assert detail.nodes == []
    assert detail.refs == []
    assert detail.links == []
