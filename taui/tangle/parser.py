from __future__ import annotations

import re
from typing import Any

from .markdown import parse_heading_tree, parse_yaml_frontmatter, slugify
from .models import (
    TangleFileMeta,
    TangleDetail,
    TangleLink,
    TangleNode,
    TangleCodeBlock,
)
from .refs import extract_tangle_refs, extract_code_blocks


MD_LINK_RE = re.compile(r"\[[^\]]+\]\((tangles/[^)#\s]+(?:#[^)\s]+)?)\)")
BARE_LINK_RE = re.compile(r"\b(tangles/[A-Za-z0-9_./\\-]+(?:#[A-Za-z0-9_./\\-]+)?)\b")


def parse_tangle_document(
    rel_path: str,
    content: str,
    *,
    file_id: int = 0,
    content_hash: str = "",
    mtime_ns: int = 0,
    last_seen: float = 0.0,
) -> TangleDetail:
    lines = content.splitlines()
    frontmatter, body_start = parse_yaml_frontmatter(lines)
    body_lines = lines[body_start:]

    title = str(frontmatter.get("title", "")).strip()
    if not title:
        title = rel_path.rsplit("/", 1)[-1].replace(".md", "").replace("-", " ").title()
    last_updated = str(frontmatter.get("last_updated", "")).strip()

    refs = extract_tangle_refs(body_lines)
    code_blocks = extract_code_blocks(body_lines)
    links = _extract_links(rel_path, body_lines)
    heading_nodes = parse_heading_tree(lines, start=body_start)

    nodes: list[TangleNode] = []
    seen_slugs: dict[str, int] = {}
    for idx, heading in enumerate(heading_nodes):
        body = "\n".join(heading.body_lines).strip()
        line_start = heading.line_index + 1
        line_end = (
            heading_nodes[idx + 1].line_index
            if idx + 1 < len(heading_nodes)
            else len(lines)
        )
        base_slug = slugify(heading.title)
        if base_slug in seen_slugs:
            count = seen_slugs[base_slug]
            anchor = f"{base_slug}-{count}"
            seen_slugs[base_slug] = count + 1
        else:
            anchor = base_slug
            seen_slugs[base_slug] = 1
        nodes.append(
            TangleNode(
                id=f"{rel_path}#{anchor}",
                tangle_path=rel_path,
                heading=heading.title,
                depth=max(0, heading.level - 1),
                anchor=anchor,
                body=body,
                refs=[],
                line_start=line_start,
                line_end=line_end,
            )
        )

    file_meta = TangleFileMeta(
        id=file_id,
        rel_path=rel_path,
        content_hash=content_hash,
        mtime_ns=mtime_ns,
        title=title,
        last_updated=last_updated,
        last_seen=last_seen,
    )
    return TangleDetail(
        file=file_meta,
        nodes=nodes,
        refs=refs,
        links=links,
        code_blocks=code_blocks,
        frontmatter=frontmatter if isinstance(frontmatter, dict) else {},
    )


def _extract_links(source_path: str, lines: list[str]) -> list[TangleLink]:
    links: list[TangleLink] = []
    for line in lines:
        md_spans: list[tuple[int, int]] = []
        for m in MD_LINK_RE.finditer(line):
            links.append(
                TangleLink(
                    source_path=source_path,
                    target_path=m.group(1),
                    link_type="markdown_link",
                )
            )
            md_spans.append(m.span())
        for m in BARE_LINK_RE.finditer(line):
            start, end = m.span()
            # Skip if this match overlaps with a markdown link match
            if any(ms <= start and end <= me for ms, me in md_spans):
                continue
            links.append(
                TangleLink(
                    source_path=source_path,
                    target_path=m.group(1),
                    link_type="bare_path",
                )
            )
    return links
