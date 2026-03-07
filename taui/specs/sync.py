from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import time
from typing import Any

from .db import NodeUpsert, SpecDB
from .errors import SpecNotFoundError, SpecValidationError
from .markdown import (
    extract_document_title_and_description,
    extract_headings,
    extract_intent_text,
    extract_status,
    parse_markdown_link,
    section_end_index,
    slugify,
)

METADATA_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\-]+)\s*:\s*([^}]+)\}\}")


@dataclass(slots=True)
class ParsedNode:
    id: str
    file_id: int
    file_rel_path: str
    spec_ref: str
    anchor: str
    title: str
    heading_level: int | None
    line_start: int | None
    line_end: int | None
    intent: str | None
    status: str | None
    content: str
    section_lines: list[str]


@dataclass(slots=True)
class ParsedFile:
    file_id: int
    rel_path: str
    abs_path: Path
    lines: list[str]
    nodes: list[ParsedNode]


class SpecSync:
    def __init__(self, *, workspace: Path, spec_root: Path, db: SpecDB) -> None:
        self.workspace = workspace
        self.spec_root = spec_root
        self.db = db

    async def full_sync(self) -> None:
        files = sorted(self.spec_root.rglob("*.md"))
        if not files:
            raise SpecNotFoundError(f"spec root does not contain markdown files: {self.spec_root}")

        now_ts = time.time()
        parsed: dict[str, ParsedFile] = {}

        for path in files:
            rel_path = self._to_rel_path(path)
            text = path.read_text(encoding="utf-8")
            content_hash = sha256(text.encode("utf-8")).hexdigest()
            mtime_ns = path.stat().st_mtime_ns
            file_row = await self.db.upsert_file(rel_path, content_hash, mtime_ns, now_ts)

            existing = await self.db.list_node_ids_by_file(file_row.id)
            lines = text.splitlines()
            nodes = self._parse_nodes(file_id=file_row.id, rel_path=rel_path, lines=lines, existing_ids=existing)
            await self.db.replace_nodes_for_file(file_row.id, [
                NodeUpsert(
                    id=node.id,
                    file_id=node.file_id,
                    spec_ref=node.spec_ref,
                    anchor=node.anchor,
                    title=node.title,
                    depth=0,
                    heading_level=node.heading_level,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    intent=node.intent,
                    status=node.status,
                    content=node.content,
                    sort_order=0,
                )
                for node in nodes
            ])
            parsed[rel_path] = ParsedFile(
                file_id=file_row.id,
                rel_path=rel_path,
                abs_path=path,
                lines=lines,
                nodes=nodes,
            )

        await self.db.delete_missing_files(set(parsed.keys()))

        # refresh node ids from DB in case removed files affected refs
        all_nodes = await self.db.get_tree()
        by_ref: dict[str, str] = {node.spec_ref: node.id for node in all_nodes}
        first_node_by_file: dict[str, str] = {}
        for node in all_nodes:
            first_node_by_file.setdefault(node.file_path, node.id)

        edges: list[tuple[str, str, int]] = []
        refs: list[tuple[str, str]] = []
        metadata: list[tuple[str, str, str]] = []
        edge_sort = 0

        for pfile in parsed.values():
            # in-file heading parentage
            heading_nodes = [node for node in pfile.nodes if node.heading_level is not None]
            for idx, node in enumerate(heading_nodes):
                parent_id: str | None = None
                for prev in reversed(heading_nodes[:idx]):
                    assert prev.heading_level is not None
                    if prev.heading_level < node.heading_level:
                        parent_id = prev.id
                        break
                if parent_id is not None:
                    edges.append((parent_id, node.id, edge_sort))
                    edge_sort += 1

            # metadata extraction
            for node in pfile.nodes:
                for line in node.section_lines[:12]:
                    for key, value in METADATA_RE.findall(line):
                        metadata.append((node.id, key.strip(), value.strip()))

            # cross-file references and edges
            for line_idx, line in enumerate(pfile.lines):
                parsed_link = parse_markdown_link(line)
                if parsed_link is None:
                    continue
                _, target = parsed_link
                target_file_rel, _, target_anchor = target.partition("#")
                target_file_rel = target_file_rel.strip()
                target_anchor = target_anchor.strip()
                if not target_file_rel.endswith(".md"):
                    continue
                resolved = (pfile.abs_path.parent / target_file_rel).resolve()
                if not self._is_within_spec_root(resolved):
                    continue
                target_rel = self._to_rel_path(resolved)
                if target_rel not in parsed:
                    continue

                source_node_id = self._source_node_for_line(pfile, line_idx)
                if source_node_id is None:
                    continue

                if target_anchor:
                    target_ref = f"{target_rel}#{target_anchor}"
                    target_node_id = by_ref.get(target_ref)
                else:
                    target_node_id = first_node_by_file.get(target_rel)

                if target_node_id is None:
                    continue
                refs.append((source_node_id, target_node_id))
                edges.append((source_node_id, target_node_id, edge_sort))
                edge_sort += 1

        await self.db.replace_node_metadata(metadata)
        await self.db.replace_node_refs(refs)
        await self.db.replace_edges(edges)

        coordinates = self._compute_tree_coordinates(parsed)
        await self.db.set_tree_coordinates(coordinates)

    async def check_for_changes(self) -> None:
        await self.full_sync()

    def _compute_tree_coordinates(self, parsed: dict[str, ParsedFile]) -> list[tuple[str, int, int]]:
        updates: list[tuple[str, int, int]] = []
        visited_files: set[str] = set()
        sort_counter = 0

        root_main = self.spec_root / "_main.md"
        root_rel = self._to_rel_path(root_main)

        def visit(rel_path: str, depth_base: int) -> None:
            nonlocal sort_counter
            if rel_path in visited_files:
                return
            pfile = parsed.get(rel_path)
            if pfile is None:
                return
            visited_files.add(rel_path)

            headings = [node for node in pfile.nodes if node.heading_level is not None]
            if not headings:
                for node in pfile.nodes:
                    updates.append((node.id, depth_base, sort_counter))
                    sort_counter += 1
            else:
                root_level = headings[0].heading_level or 1
                for node in headings:
                    level = node.heading_level or root_level
                    depth = depth_base + max(0, level - root_level)
                    updates.append((node.id, depth, sort_counter))
                    sort_counter += 1

            seen_children: set[str] = set()
            for line in pfile.lines:
                link = parse_markdown_link(line)
                if link is None:
                    continue
                _, target = link
                target_file = target.split("#", 1)[0].strip()
                if not target_file.endswith(".md"):
                    continue
                resolved = (pfile.abs_path.parent / target_file).resolve()
                if not self._is_within_spec_root(resolved):
                    continue
                child_rel = self._to_rel_path(resolved)
                if child_rel in seen_children:
                    continue
                seen_children.add(child_rel)
                visit(child_rel, depth_base + 1)

        if root_rel in parsed:
            visit(root_rel, 1)

        for rel_path in sorted(parsed.keys()):
            if rel_path not in visited_files:
                visit(rel_path, 1)

        return updates

    def _source_node_for_line(self, pfile: ParsedFile, line_idx: int) -> str | None:
        if not pfile.nodes:
            return None
        headings = [node for node in pfile.nodes if node.heading_level is not None and node.line_start is not None]
        if not headings:
            return pfile.nodes[0].id
        chosen = headings[0]
        for node in headings:
            assert node.line_start is not None
            if node.line_start - 1 <= line_idx:
                chosen = node
            else:
                break
        return chosen.id

    def _parse_nodes(
        self,
        *,
        file_id: int,
        rel_path: str,
        lines: list[str],
        existing_ids: dict[str, str],
    ) -> list[ParsedNode]:
        out: list[ParsedNode] = []
        headings = extract_headings(lines)

        if not headings:
            parsed = extract_document_title_and_description(lines)
            if parsed is None:
                return out
            title, intent, title_line = parsed
            anchor = slugify(title)
            node_id = existing_ids.get(anchor) or self.db.new_node_id()
            start = title_line + 1
            section_lines = lines[start:]
            out.append(
                ParsedNode(
                    id=node_id,
                    file_id=file_id,
                    file_rel_path=rel_path,
                    spec_ref=f"{rel_path}#{anchor}",
                    anchor=anchor,
                    title=title,
                    heading_level=None,
                    line_start=start + 1 if lines else None,
                    line_end=len(lines) if lines else None,
                    intent=intent,
                    status=extract_status(lines, start, len(lines)),
                    content="\n".join(section_lines).strip("\n"),
                    section_lines=section_lines,
                )
            )
            return out

        for idx, heading in enumerate(headings):
            start = heading.line_index + 1
            end = section_end_index(headings, idx, len(lines), include_children=False)
            section_lines = lines[start:end]
            anchor = slugify(heading.title)
            node_id = existing_ids.get(anchor) or self.db.new_node_id()
            out.append(
                ParsedNode(
                    id=node_id,
                    file_id=file_id,
                    file_rel_path=rel_path,
                    spec_ref=f"{rel_path}#{anchor}",
                    anchor=anchor,
                    title=heading.title,
                    heading_level=heading.level,
                    line_start=heading.line_index + 1,
                    line_end=end,
                    intent=extract_intent_text(lines, start, end),
                    status=extract_status(lines, start, end),
                    content="\n".join(section_lines).strip("\n"),
                    section_lines=section_lines,
                )
            )
        return out

    def _is_within_spec_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.spec_root)
        except ValueError:
            return False
        return True

    def _to_rel_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError as exc:
            raise SpecValidationError(f"path is outside workspace: {path}") from exc
