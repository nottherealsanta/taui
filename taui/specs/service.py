from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time

from .db import SpecDB
from .errors import SpecNotFoundError, SpecValidationError
from .markdown import find_intent_line, parse_markdown_link, slugify
from .models import SpecNode, SpecNodeDetail, SpecNodePatch, SpecUpdateResult, UNSET
from .sync import SpecSync
from .writer import SpecMarkdownWriter

logger = logging.getLogger(__name__)


class SpecService:
    """Loads and mutates the spec tree through the SQLite backing store."""

    def __init__(
        self,
        workspace: Path | str | None = None,
        specs_path: Path | str | None = None,
        specs_dir: str = "specs",
    ) -> None:
        self.workspace = Path(workspace or Path.cwd()).resolve()
        if specs_path is None:
            self.spec_root = (self.workspace / specs_dir).resolve()
        else:
            candidate = Path(specs_path)
            if not candidate.is_absolute():
                candidate = self.workspace / candidate
            self.spec_root = candidate.resolve()

        if not self.spec_root.exists():
            raise SpecNotFoundError(f"spec root does not exist: {self.spec_root}")
        if not self.spec_root.is_dir():
            raise SpecValidationError(f"spec root is not a directory: {self.spec_root}")

        self.db = SpecDB(self.workspace)
        self.sync = SpecSync(workspace=self.workspace, spec_root=self.spec_root, db=self.db)
        self.writer = SpecMarkdownWriter(workspace=self.workspace, db=self.db)
        self._initialized = False
        self._init_lock = asyncio.Lock()
        logger.info(
            "SpecService created workspace=%s spec_root=%s db_path=%s",
            self.workspace,
            self.spec_root,
            self.db.db_path,
        )

    async def ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            started = time.perf_counter()
            logger.info("SpecService initialization started")
            await self.db.connect()
            await self.sync.full_sync()
            self._initialized = True
            logger.info(
                "SpecService initialization complete duration_ms=%s",
                int((time.perf_counter() - started) * 1000),
            )

    async def get_tree(self) -> list[SpecNode]:
        await self.ensure_initialized()
        nodes = await self.db.get_tree()
        logger.debug("Spec tree loaded node_count=%s", len(nodes))
        return nodes

    async def get_node(self, spec_ref: str) -> SpecNodeDetail:
        await self.ensure_initialized()
        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            logger.warning("Spec node not found spec_ref=%s", spec_ref)
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        logger.debug("Spec node loaded spec_ref=%s node_id=%s", spec_ref, node.id)
        return node

    async def update_node(
        self, spec_ref: str, patch: SpecNodePatch | dict[str, object]
    ) -> SpecUpdateResult:
        await self.ensure_initialized()
        started = time.perf_counter()
        patch_obj = patch if isinstance(patch, SpecNodePatch) else SpecNodePatch.from_mapping(patch)
        patch_keys = [
            key
            for key, value in (
                ("title", patch_obj.title),
                ("intent", patch_obj.intent),
                ("content", patch_obj.content),
            )
            if value is not UNSET
        ]
        logger.info("Updating spec node spec_ref=%s patch_fields=%s", spec_ref, patch_keys)
        if patch_obj.intent is not UNSET and patch_obj.content is not UNSET:
            raise SpecValidationError("patch cannot set both 'intent' and 'content' together")

        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        raw = await self.db._one(
            "SELECT file_id, heading_level FROM nodes WHERE id = ?",
            (node.id,),
        )
        if raw is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        file_id = int(raw["file_id"])

        if patch_obj.content is not UNSET:
            child_count = await self._count_in_file_children(node.id)
            heading_level = raw.get("heading_level")
            if heading_level is not None and child_count > 0:
                raise SpecValidationError("content updates are only allowed on leaf headings")

        new_title = node.title
        new_content = node.content

        if patch_obj.title is not UNSET:
            if patch_obj.title is None or not patch_obj.title.strip():
                raise SpecValidationError("title cannot be empty")
            new_title = patch_obj.title.strip()

        if patch_obj.content is not UNSET:
            new_content = patch_obj.content or ""

        if patch_obj.intent is not UNSET:
            new_content = self._apply_intent_patch(new_content, patch_obj.intent)

        new_anchor = slugify(new_title)
        rel_path = node.file_path
        new_ref = f"{rel_path}#{new_anchor}"
        new_intent = self._extract_intent_from_content(new_content)
        new_status = self._extract_status_from_content(new_content)

        await self.db.update_node(
            node.id,
            spec_ref=new_ref,
            anchor=new_anchor,
            title=new_title,
            intent=new_intent,
            status=new_status,
            content=new_content,
        )

        # Keep in-file markdown links on rename consistent for local anchors.
        if new_ref != spec_ref:
            await self._rewrite_in_file_anchor_refs(file_id=file_id, old_anchor=node.anchor, new_anchor=new_anchor)

        updated = await self.db.get_node(node.id)
        assert updated is not None

        self.writer.schedule_writeback(file_id)
        logger.info(
            "Spec node updated old_ref=%s new_ref=%s tree_changed=%s duration_ms=%s",
            spec_ref,
            new_ref,
            new_ref != spec_ref,
            int((time.perf_counter() - started) * 1000),
        )

        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=updated,
            tree_changed=(new_ref != spec_ref),
        )

    async def _count_in_file_children(self, node_id: str) -> int:
        row = await self.db._one(
            """
SELECT COUNT(*) AS c
FROM edges e
JOIN nodes n ON n.id = e.child_id
WHERE e.parent_id = ?
  AND n.file_id = (SELECT file_id FROM nodes WHERE id = ?)
""",
            (node_id, node_id),
        )
        return int(row["c"]) if row is not None else 0

    def _apply_intent_patch(self, content: str, intent: str | None | object) -> str:
        lines = content.splitlines()
        intent_idx = find_intent_line(lines, 0, len(lines))
        if intent is None or not str(intent).strip():
            if intent_idx is not None:
                del lines[intent_idx]
            return "\n".join(lines).strip("\n")

        new_intent = str(intent).strip()
        if intent_idx is None:
            lines.insert(0, new_intent)
        else:
            lines[intent_idx] = new_intent
        return "\n".join(lines).strip("\n")

    def _extract_intent_from_content(self, content: str) -> str | None:
        lines = content.splitlines()
        idx = find_intent_line(lines, 0, len(lines))
        if idx is None:
            return None
        value = lines[idx].strip()
        return value or None

    def _extract_status_from_content(self, content: str) -> str | None:
        lines = content.splitlines()
        scan_end = min(8, len(lines))
        for line in lines[:scan_end]:
            marker = "{{status:"
            if marker not in line:
                continue
            tail = line.split(marker, 1)[1]
            end = tail.find("}}")
            if end < 0:
                continue
            status = tail[:end].strip()
            if status:
                return status
        return None

    async def _rewrite_in_file_anchor_refs(self, *, file_id: int, old_anchor: str, new_anchor: str) -> None:
        nodes = await self.db.get_nodes_for_file(file_id)
        updated_any = False
        changed_nodes = 0
        for node in nodes:
            lines = node.content.splitlines()
            changed = False
            for idx, line in enumerate(lines):
                link = parse_markdown_link(line)
                if link is None:
                    continue
                text, target = link
                rel, sep, anchor = target.partition("#")
                if rel.strip() and rel.strip() != node.file_path:
                    continue
                if not sep or anchor.strip() != old_anchor:
                    continue
                next_target = f"#{new_anchor}" if not rel.strip() else f"{rel}#{new_anchor}"
                lines[idx] = line.replace(f"[{text}]({target})", f"[{text}]({next_target})")
                changed = True
            if not changed:
                continue
            updated_any = True
            changed_nodes += 1
            new_content = "\n".join(lines).strip("\n")
            await self.db.update_node(
                node.id,
                spec_ref=node.spec_ref,
                anchor=node.anchor,
                title=node.title,
                intent=self._extract_intent_from_content(new_content),
                status=self._extract_status_from_content(new_content),
                content=new_content,
            )
        if updated_any:
            self.writer.schedule_writeback(file_id)
            logger.debug(
                "Rewrote in-file anchor refs file_id=%s old_anchor=%s new_anchor=%s changed_nodes=%s",
                file_id,
                old_anchor,
                new_anchor,
                changed_nodes,
            )
