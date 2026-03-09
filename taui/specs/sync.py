from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import time

from .db import NodeUpsert, SpecDB
from .errors import SpecNotFoundError, SpecValidationError
from .markdown import (
    parse_list_items,
    parse_markdown_link,
    parse_wiki_link,
    slugify,
    strip_inline_metadata,
)

METADATA_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\-]+)\s*:\s*([^}]+)\}\}")


@dataclass(slots=True)
class ParsedNode:
    id: str
    file_id: int
    file_rel_path: str
    spec_ref: str
    anchor: str
    heading_level: int | None
    line_start: int | None
    line_end: int | None
    markdown: str
    lines: list[str]


@dataclass(slots=True)
class ParsedInclude:
    line_index: int
    heading_level: int
    parent_node_id: str | None
    target: str


@dataclass(slots=True)
class ParsedFile:
    file_id: int
    rel_path: str
    abs_path: Path
    lines: list[str]
    nodes: list[ParsedNode]
    includes: list[ParsedInclude]
    in_file_edges: list[tuple[str, str]]


class SpecSync:
    def __init__(self, *, workspace: Path, spec_root: Path, db: SpecDB) -> None:
        self.workspace = workspace
        self.spec_root = spec_root
        self.db = db

    async def full_sync(self) -> None:
        files = sorted(self.spec_root.rglob("*.md"))
        if not files:
            raise SpecNotFoundError(
                f"spec root does not contain markdown files: {self.spec_root}"
            )

        now_ts = time.time()
        parsed: dict[str, ParsedFile] = {}

        for path in files:
            rel_path = self._to_rel_path(path)
            text = path.read_text(encoding="utf-8")
            content_hash = sha256(text.encode("utf-8")).hexdigest()
            mtime_ns = path.stat().st_mtime_ns
            file_row = await self.db.upsert_file(
                rel_path, content_hash, mtime_ns, now_ts
            )

            existing = await self.db.list_node_ids_by_file(file_row.id)
            lines = text.splitlines()
            nodes, includes, in_file_edges = self._parse_nodes(
                file_id=file_row.id,
                rel_path=rel_path,
                lines=lines,
                existing_ids=existing,
            )
            await self.db.replace_nodes_for_file(
                file_row.id,
                [
                    NodeUpsert(
                        id=node.id,
                        file_id=node.file_id,
                        spec_ref=node.spec_ref,
                        anchor=node.anchor,
                        depth=0,
                        heading_level=node.heading_level,
                        line_start=node.line_start,
                        line_end=node.line_end,
                        markdown=node.markdown,
                        sort_order=0,
                    )
                    for node in nodes
                ],
            )
            parsed[rel_path] = ParsedFile(
                file_id=file_row.id,
                rel_path=rel_path,
                abs_path=path,
                lines=lines,
                nodes=nodes,
                includes=includes,
                in_file_edges=in_file_edges,
            )

        await self.db.delete_missing_files(set(parsed.keys()))

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
            for parent_id, child_id in pfile.in_file_edges:
                edges.append((parent_id, child_id, edge_sort))
                edge_sort += 1

            for node in pfile.nodes:
                scan_lines = node.lines
                for line in scan_lines[:12]:
                    for key, value in METADATA_RE.findall(line):
                        metadata.append((node.id, key.strip(), value.strip()))

            for node in pfile.nodes:
                scan_lines = node.lines
                for line in scan_lines:
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

                    if target_anchor:
                        target_ref = f"{target_rel}#{target_anchor}"
                        target_node_id = by_ref.get(target_ref)
                    else:
                        target_node_id = first_node_by_file.get(target_rel)

                    if target_node_id is None:
                        continue
                    refs.append((node.id, target_node_id))

            for include in pfile.includes:
                target_file_rel, _, target_anchor = include.target.partition("#")
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

                if target_anchor:
                    target_ref = f"{target_rel}#{target_anchor}"
                    target_node_id = by_ref.get(target_ref)
                else:
                    target_node_id = first_node_by_file.get(target_rel)

                if target_node_id is None:
                    continue
                if include.parent_node_id is not None:
                    edges.append((include.parent_node_id, target_node_id, edge_sort))
                    edge_sort += 1

        await self.db.replace_node_metadata(metadata)
        await self.db.replace_node_refs(refs)
        await self.db.replace_edges(edges)

        coordinates = self._compute_tree_coordinates(parsed)
        await self.db.set_tree_coordinates(coordinates)

    async def check_for_changes(self) -> None:
        await self.full_sync()

    def _compute_tree_coordinates(
        self, parsed: dict[str, ParsedFile]
    ) -> list[tuple[str, int, int]]:
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

            if not pfile.nodes:
                return

            min_level = min(node.heading_level or 1 for node in pfile.nodes)
            nodes_by_line = {
                (node.line_start - 1 if node.line_start is not None else 0): node
                for node in pfile.nodes
            }
            include_by_line = {
                include.line_index: include for include in pfile.includes
            }
            line_indexes = sorted(set([*nodes_by_line.keys(), *include_by_line.keys()]))

            for line_index in line_indexes:
                node = nodes_by_line.get(line_index)
                if node is not None:
                    level = node.heading_level or min_level
                    depth = depth_base + max(0, level - min_level)
                    updates.append((node.id, depth, sort_counter))
                    sort_counter += 1

                include = include_by_line.get(line_index)
                if include is None:
                    continue
                target_file = include.target.split("#", 1)[0].strip()
                if not target_file.endswith(".md"):
                    continue
                resolved = (pfile.abs_path.parent / target_file).resolve()
                if not self._is_within_spec_root(resolved):
                    continue
                child_rel = self._to_rel_path(resolved)
                child_depth_base = depth_base + max(
                    0, include.heading_level - min_level
                )
                visit(child_rel, child_depth_base)

        if root_rel in parsed:
            visit(root_rel, 1)

        for rel_path in sorted(parsed.keys()):
            if rel_path not in visited_files:
                visit(rel_path, 1)

        return updates

    def _parse_nodes(
        self,
        *,
        file_id: int,
        rel_path: str,
        lines: list[str],
        existing_ids: dict[str, str],
    ) -> tuple[list[ParsedNode], list[ParsedInclude], list[tuple[str, str]]]:
        out: list[ParsedNode] = []
        includes: list[ParsedInclude] = []
        in_file_edges: list[tuple[str, str]] = []

        list_items = parse_list_items(lines, indent_size=4)
        if not list_items:
            return out, includes, in_file_edges

        next_break_by_index: dict[int, int] = {}
        for idx, item in enumerate(list_items):
            next_break = len(lines)
            for later in list_items[idx + 1 :]:
                if later.depth <= item.depth:
                    next_break = later.line_index
                    break
            next_break_by_index[idx] = next_break

        item_to_node_id: dict[int, str] = {}
        item_parent_index: dict[int, int | None] = {
            idx: item.parent_index for idx, item in enumerate(list_items)
        }
        used_anchors: set[str] = set()

        for idx, item in enumerate(list_items):
            include_target = parse_wiki_link(item.title)
            if include_target is not None:
                parent_idx = item.parent_index
                parent_node_id: str | None = None
                while parent_idx is not None:
                    parent_node_id = item_to_node_id.get(parent_idx)
                    if parent_node_id is not None:
                        break
                    parent_idx = item_parent_index.get(parent_idx)
                includes.append(
                    ParsedInclude(
                        line_index=item.line_index,
                        heading_level=item.depth + 1,
                        parent_node_id=parent_node_id,
                        target=include_target,
                    )
                )
                continue

            title = strip_inline_metadata(item.title)
            if not title:
                title = item.title.strip()

            base_anchor = slugify(title)
            anchor = base_anchor
            suffix = 1
            while anchor in used_anchors:
                anchor = f"{base_anchor}-{suffix}"
                suffix += 1
            used_anchors.add(anchor)
            node_id = existing_ids.get(anchor) or self.db.new_node_id()
            item_to_node_id[idx] = node_id

            end = next_break_by_index[idx]
            node_lines = [item.title.strip(), *item.content_lines]
            parsed_node = ParsedNode(
                id=node_id,
                file_id=file_id,
                file_rel_path=rel_path,
                spec_ref=f"{rel_path}#{anchor}",
                anchor=anchor,
                heading_level=item.depth + 1,
                line_start=item.line_index + 1,
                line_end=end,
                markdown="\n".join(node_lines).strip("\n"),
                lines=node_lines,
            )
            out.append(parsed_node)

            parent_idx = item.parent_index
            while parent_idx is not None:
                parent_id = item_to_node_id.get(parent_idx)
                if parent_id is not None:
                    in_file_edges.append((parent_id, node_id))
                    break
                parent_idx = item_parent_index.get(parent_idx)

        return out, includes, in_file_edges

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
