from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from .db import NodeUpsert, SpecDB
from .errors import SpecNotFoundError, SpecValidationError
from .markdown import (
    parse_list_items,
    parse_markdown_link,
    slugify,
    strip_inline_metadata,
)

METADATA_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\\\-]+)\s*:\s*([^}]+)\}\}")
METADATA_ITEM_RE = re.compile(r"^\{\{\s*([a-zA-Z0-9_\\\-]+)\s*:\s*(.+?)\s*\}\}$")


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
    status: str | None = None
    code_refs: list[str] = field(default_factory=list)
    verification: str | None = None
    collapsed: bool = False
    depends_on_targets: list[str] = field(default_factory=list)
    related_to_targets: list[str] = field(default_factory=list)


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
                        status=node.status,
                        code_refs=(
                            json.dumps(node.code_refs) if node.code_refs else None
                        ),
                        verification=node.verification,
                        collapsed=1 if node.collapsed else 0,
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
        refs: list[tuple[str, str, str]] = []
        edge_sort = 0

        for pfile in parsed.values():
            for parent_id, child_id in pfile.in_file_edges:
                edges.append((parent_id, child_id, edge_sort))
                edge_sort += 1

            for node in pfile.nodes:
                for target in node.depends_on_targets:
                    target_node_id = self._resolve_ref_target(
                        target=target,
                        file_abs_path=pfile.abs_path,
                        parsed=parsed,
                        by_ref=by_ref,
                        first_node_by_file=first_node_by_file,
                    )
                    if target_node_id is not None:
                        refs.append((node.id, target_node_id, "depends_on"))

                for target in node.related_to_targets:
                    target_node_id = self._resolve_ref_target(
                        target=target,
                        file_abs_path=pfile.abs_path,
                        parsed=parsed,
                        by_ref=by_ref,
                        first_node_by_file=first_node_by_file,
                    )
                    if target_node_id is not None:
                        refs.append((node.id, target_node_id, "related_to"))

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

        node_by_id: dict[str, ParsedNode] = {}

        def nearest_parent_node_id(item_index: int) -> str | None:
            parent_idx = item_parent_index.get(item_index)
            while parent_idx is not None:
                parent_node_id = item_to_node_id.get(parent_idx)
                if parent_node_id is not None:
                    return parent_node_id
                parent_idx = item_parent_index.get(parent_idx)
            return None

        for idx, item in enumerate(list_items):
            # Check for {{tree: [Title](./file.md)}} tree expansion metadata
            tree_match = METADATA_ITEM_RE.match(item.title.strip())
            if tree_match is not None and tree_match.group(1).strip().lower() == "tree":
                parent_node_id = nearest_parent_node_id(idx)
                tree_value = tree_match.group(2).strip()
                parsed_link = parse_markdown_link(tree_value)
                include_target = (
                    parsed_link[1] if parsed_link is not None else tree_value
                )
                if include_target:
                    includes.append(
                        ParsedInclude(
                            line_index=item.line_index,
                            heading_level=item.depth + 1,
                            parent_node_id=parent_node_id,
                            target=include_target,
                        )
                    )
                continue

            metadata_match = METADATA_ITEM_RE.match(item.title.strip())
            if metadata_match is not None:
                parent_node_id = nearest_parent_node_id(idx)
                if parent_node_id is not None:
                    parent_node = node_by_id[parent_node_id]
                    self._apply_metadata(
                        node=parent_node,
                        key=metadata_match.group(1),
                        value=metadata_match.group(2),
                    )
                    for raw_line in item.content_lines:
                        nested = METADATA_ITEM_RE.match(raw_line.strip())
                        if nested is None:
                            continue
                        self._apply_metadata(
                            node=parent_node,
                            key=nested.group(1),
                            value=nested.group(2),
                        )
                continue

            title, inline_metadata = self._strip_title_metadata(item.title.strip())
            if not title:
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
            node_lines: list[str] = [title]

            parsed_node = ParsedNode(
                id=node_id,
                file_id=file_id,
                file_rel_path=rel_path,
                spec_ref=f"{rel_path}#{anchor}",
                anchor=anchor,
                heading_level=item.depth + 1,
                line_start=item.line_index + 1,
                line_end=end,
                markdown="",
                lines=[],
            )
            node_by_id[node_id] = parsed_node

            for key, value in inline_metadata:
                self._apply_metadata(node=parsed_node, key=key, value=value)

            for raw_line in item.content_lines:
                content_line = raw_line.strip()
                metadata_line = METADATA_ITEM_RE.match(content_line)
                if metadata_line is not None:
                    self._apply_metadata(
                        node=parsed_node,
                        key=metadata_line.group(1),
                        value=metadata_line.group(2),
                    )
                    continue
                node_lines.append(raw_line)

            parsed_node.markdown = "\n".join(node_lines).strip("\n")
            parsed_node.lines = node_lines
            out.append(parsed_node)

            parent_idx = item.parent_index
            while parent_idx is not None:
                parent_id = item_to_node_id.get(parent_idx)
                if parent_id is not None:
                    in_file_edges.append((parent_id, node_id))
                    break
                parent_idx = item_parent_index.get(parent_idx)

        return out, includes, in_file_edges

    def _strip_title_metadata(self, title: str) -> tuple[str, list[tuple[str, str]]]:
        extracted = [(k.strip(), v.strip()) for k, v in METADATA_RE.findall(title)]
        clean = strip_inline_metadata(title)
        return clean, extracted

    def _normalize_status(self, value: str) -> str:
        normalized = value.strip().replace("-", "_")
        return normalized

    def _apply_metadata(self, *, node: ParsedNode, key: str, value: str) -> None:
        key_name = key.strip().lower().replace("\\", "")
        value_text = value.strip()
        if key_name == "status":
            node.status = self._normalize_status(value_text)
            return
        if key_name == "code_ref":
            cleaned = value_text.strip("`").replace("\\_", "_")
            if cleaned:
                node.code_refs.append(cleaned)
            return
        if key_name == "verification":
            node.verification = value_text
            return
        if key_name == "collapsed":
            node.collapsed = value_text.lower() in {"true", "1", "yes"}
            return
        if key_name in {"depends_on", "related_to"}:
            parsed = parse_markdown_link(value_text)
            target = parsed[1] if parsed is not None else value_text
            if not target:
                return
            if key_name == "depends_on":
                node.depends_on_targets.append(target)
            else:
                node.related_to_targets.append(target)

    def _resolve_ref_target(
        self,
        *,
        target: str,
        file_abs_path: Path,
        parsed: dict[str, ParsedFile],
        by_ref: dict[str, str],
        first_node_by_file: dict[str, str],
    ) -> str | None:
        target_file_rel, _, target_anchor = target.partition("#")
        target_file_rel = target_file_rel.strip()
        target_anchor = target_anchor.strip()
        if not target_file_rel and target_anchor:
            target_rel = self._to_rel_path(file_abs_path)
            return by_ref.get(f"{target_rel}#{target_anchor}")
        if not target_file_rel.endswith(".md"):
            return None
        resolved = (file_abs_path.parent / target_file_rel).resolve()
        if not self._is_within_spec_root(resolved):
            return None
        target_rel = self._to_rel_path(resolved)
        if target_rel not in parsed:
            return None
        if target_anchor:
            return by_ref.get(f"{target_rel}#{target_anchor}")
        return first_node_by_file.get(target_rel)

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
