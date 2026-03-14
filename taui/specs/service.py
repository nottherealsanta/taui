from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
import time
from uuid import uuid4

from .db import SpecDB
from .errors import SpecNotFoundError, SpecValidationError, SpecServiceError
from .markdown import markdown_anchor_text, parse_markdown_link, slugify
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
        dev_mode: bool = False,
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

        self.db = SpecDB(self.workspace, persist_snapshot=not dev_mode)
        self.sync = SpecSync(
            workspace=self.workspace, spec_root=self.spec_root, db=self.db
        )
        self.writer = SpecMarkdownWriter(workspace=self.workspace, db=self.db)
        self._initialized = False
        self._init_lock = asyncio.Lock()
        logger.info(
            "SpecService created workspace=%s spec_root=%s db_path=%s dev_mode=%s",
            self.workspace,
            self.spec_root,
            self.db.db_path,
            dev_mode,
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

    @contextlib.asynccontextmanager
    async def defer_writeback(self):
        """Context manager: suppress debounced per-mutation writeback.

        While active, all ``schedule_writeback()`` calls only mark files dirty.
        On exit the context manager flushes all dirty files in one batch write.

        Use this around agent task execution so that many spec mutations during
        a single task are written out as one batch rather than many debounced
        individual writes.

        Example::

            async with spec_service.defer_writeback():
                # agent does many spec mutations here
                ...
            # all dirty files are now flushed
        """
        self.writer._deferred = True
        try:
            yield
        finally:
            self.writer._deferred = False
            await self.writer.flush_all_files()
            logger.info(
                "SpecService.defer_writeback: flushed all dirty files after agent task"
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

    async def set_node_collapsed(
        self, spec_ref: str, collapsed: bool
    ) -> SpecNodeDetail:
        await self.ensure_initialized()
        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        await self.db.set_node_collapsed(node.id, collapsed)
        updated = await self.db.get_node(node.id)
        assert updated is not None
        return updated

    async def update_node(
        self, spec_ref: str, patch: SpecNodePatch | dict[str, object]
    ) -> SpecUpdateResult:
        await self.ensure_initialized()
        started = time.perf_counter()
        patch_obj = (
            patch
            if isinstance(patch, SpecNodePatch)
            else SpecNodePatch.from_mapping(patch)
        )
        patch_keys = [
            key
            for key, value in (("markdown", patch_obj.markdown),)
            if value is not UNSET
        ]
        logger.info(
            "Updating spec node spec_ref=%s patch_fields=%s", spec_ref, patch_keys
        )

        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        raw = await self.db._one(
            "SELECT file_id FROM nodes WHERE id = ?",
            (node.id,),
        )
        if raw is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")
        file_id = int(raw["file_id"])

        new_markdown = node.markdown
        if patch_obj.markdown is not UNSET:
            new_markdown = patch_obj.markdown or ""

        desired_anchor = slugify(markdown_anchor_text(new_markdown))
        new_anchor = await self._ensure_unique_anchor(
            file_id=file_id, node_id=node.id, desired=desired_anchor
        )
        rel_path = node.file_path
        new_ref = f"{rel_path}#{new_anchor}"

        await self.db.update_node(
            node.id,
            spec_ref=new_ref,
            anchor=new_anchor,
            markdown=new_markdown,
        )

        # Keep in-file markdown links on rename consistent for local anchors.
        if new_ref != spec_ref:
            await self._rewrite_in_file_anchor_refs(
                file_id=file_id, old_anchor=node.anchor, new_anchor=new_anchor
            )

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

    async def _ensure_unique_anchor(
        self, *, file_id: int, node_id: str | None, desired: str
    ) -> str:
        existing_rows = await self.db._all(
            "SELECT id, anchor FROM nodes WHERE file_id = ?",
            (file_id,),
        )
        existing = {
            str(row["anchor"])
            for row in existing_rows
            if node_id is None or str(row["id"]) != node_id
        }

        if desired not in existing:
            return desired

        base = desired
        counter = 1
        candidate = f"{base}-{counter}"
        while candidate in existing:
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    async def _rewrite_in_file_anchor_refs(
        self, *, file_id: int, old_anchor: str, new_anchor: str
    ) -> None:
        nodes = await self.db.get_nodes_for_file(file_id)
        updated_any = False
        changed_nodes = 0
        for node in nodes:
            lines = node.markdown.splitlines()
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
                next_target = (
                    f"#{new_anchor}" if not rel.strip() else f"{rel}#{new_anchor}"
                )
                lines[idx] = line.replace(
                    f"[{text}]({target})", f"[{text}]({next_target})"
                )
                changed = True
            if not changed:
                continue
            updated_any = True
            changed_nodes += 1
            new_markdown = "\n".join(lines).strip("\n")
            await self.db.update_node(
                node.id,
                spec_ref=node.spec_ref,
                anchor=node.anchor,
                markdown=new_markdown,
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

    # ------------------------------------------------------------------ #
    # Structural editing: create sibling, indent, outdent                 #
    # ------------------------------------------------------------------ #

    async def create_sibling_node(self, spec_ref: str) -> SpecUpdateResult:
        """Insert a new empty node as the next sibling of the given node.

        Constraints (v1): same file only. Raises SpecValidationError when the
        target node has no heading level (plain-document nodes) or when the
        operation would require cross-file moves.
        """
        await self.ensure_initialized()
        anchor_node = await self.db.get_node_by_ref(spec_ref)
        if anchor_node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        raw = await self.db._one(
            "SELECT file_id, heading_level, sort_order FROM nodes WHERE id = ?",
            (anchor_node.id,),
        )
        if raw is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        heading_level = raw.get("heading_level")
        if heading_level is None:
            raise SpecValidationError(
                "create_sibling_node is only supported for heading nodes"
            )

        file_id = int(raw["file_id"])
        anchor_sort = int(raw["sort_order"])

        # Build a unique anchor/spec_ref for the new node.
        new_markdown = ""
        new_anchor = slugify(markdown_anchor_text(new_markdown))
        rel_path = anchor_node.file_path
        new_anchor = await self._ensure_unique_anchor(
            file_id=file_id, node_id=None, desired=new_anchor
        )

        new_spec_ref = f"{rel_path}#{new_anchor}"
        new_id = str(uuid4())
        now_ts = time.time()
        new_sort = anchor_sort + 1

        # Shift all nodes after the anchor down by 1 in sort_order.
        await self.db._execute(
            "UPDATE nodes SET sort_order = sort_order + 1 WHERE file_id = ? AND sort_order > ?",
            (file_id, anchor_sort),
        )
        await self.db._conn.commit()

        # Determine parent of anchor node so we can insert edge correctly.
        parent_edge = await self.db._one(
            "SELECT parent_id FROM edges WHERE child_id = ?",
            (anchor_node.id,),
        )
        parent_id = parent_edge["parent_id"] if parent_edge else None

        # Insert the new node.
        await self.db._execute(
            """
INSERT INTO nodes(
    id, file_id, spec_ref, anchor, depth, heading_level,
    line_start, line_end, markdown, sort_order, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
""",
            (
                new_id,
                file_id,
                new_spec_ref,
                new_anchor,
                anchor_node.depth,
                heading_level,
                new_markdown,
                new_sort,
                now_ts,
                now_ts,
            ),
        )
        await self.db._conn.commit()

        # Wire edge to same parent as anchor node, inserted immediately after the anchor.
        if parent_id is not None:
            anchor_edge = await self.db._one(
                "SELECT sort_order FROM edges WHERE parent_id = ? AND child_id = ?",
                (parent_id, anchor_node.id),
            )
            anchor_edge_sort = int(anchor_edge["sort_order"]) if anchor_edge else 0
            # Shift all edges after the anchor position down by 1 to make room.
            await self.db._execute(
                "UPDATE edges SET sort_order = sort_order + 1 WHERE parent_id = ? AND sort_order > ?",
                (parent_id, anchor_edge_sort),
            )
            await self.db._execute(
                "INSERT OR IGNORE INTO edges(parent_id, child_id, sort_order) VALUES (?, ?, ?)",
                (parent_id, new_id, anchor_edge_sort + 1),
            )
            await self.db._conn.commit()

        self.writer.schedule_writeback(file_id)
        logger.info(
            "Created sibling node after spec_ref=%s new_spec_ref=%s",
            spec_ref,
            new_spec_ref,
        )

        new_node = await self.db.get_node(new_id)
        assert new_node is not None
        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=new_node,
            tree_changed=True,
        )

    async def indent_node(self, spec_ref: str) -> SpecUpdateResult:
        """Make the node a child of its previous sibling (heading level +1).

        v1 constraint: same-file structural edits only.
        """
        await self.ensure_initialized()
        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        raw = await self.db._one(
            "SELECT file_id, heading_level, sort_order FROM nodes WHERE id = ?",
            (node.id,),
        )
        if raw is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        heading_level = raw.get("heading_level")
        if heading_level is None:
            raise SpecValidationError("indent_node is only supported for heading nodes")
        file_id = int(raw["file_id"])

        # Find the previous sibling by sort_order within same parent.
        parent_edge = await self.db._one(
            "SELECT parent_id FROM edges WHERE child_id = ?",
            (node.id,),
        )
        if parent_edge:
            siblings = await self.db.get_children(parent_edge["parent_id"])
        else:
            # Root-level nodes: siblings are nodes with no parent edge.
            all_nodes = await self.db.get_tree()
            siblings = [
                n
                for n in all_nodes
                if await self.db._one("SELECT 1 FROM edges WHERE child_id = ?", (n.id,))
                is None
            ]

        node_index = next((i for i, s in enumerate(siblings) if s.id == node.id), None)
        if node_index is None or node_index == 0:
            raise SpecValidationError(
                "cannot indent: no previous sibling to become parent"
            )

        new_parent = siblings[node_index - 1]
        new_parent_raw = await self.db._one(
            "SELECT file_id, heading_level FROM nodes WHERE id = ?",
            (new_parent.id,),
        )
        if new_parent_raw is None:
            raise SpecServiceError("previous sibling not found")

        if int(new_parent_raw["file_id"]) != file_id:
            raise SpecValidationError("cross-file indent is not supported in v1")

        new_heading_level = heading_level + 1

        now = time.time()
        await self.db._execute(
            "UPDATE nodes SET heading_level = ?, depth = depth + 1, updated_at = ? WHERE id = ?",
            (new_heading_level, now, node.id),
        )

        # Recursively update all descendants: depth +1, heading_level +1 (if heading).
        descendants = await self.db.get_subtree(node.id)
        for desc in descendants:
            desc_raw = await self.db._one(
                "SELECT heading_level FROM nodes WHERE id = ?", (desc.id,)
            )
            if desc_raw and desc_raw["heading_level"] is not None:
                await self.db._execute(
                    "UPDATE nodes SET depth = depth + 1, heading_level = heading_level + 1, updated_at = ? WHERE id = ?",
                    (now, desc.id),
                )
            else:
                await self.db._execute(
                    "UPDATE nodes SET depth = depth + 1, updated_at = ? WHERE id = ?",
                    (now, desc.id),
                )

        # Re-wire edge: remove old parent edge, add new one under new_parent.
        if parent_edge:
            await self.db._execute(
                "DELETE FROM edges WHERE child_id = ?",
                (node.id,),
            )
        new_parent_children = await self.db.get_children(new_parent.id)
        await self.db._execute(
            "INSERT OR IGNORE INTO edges(parent_id, child_id, sort_order) VALUES (?, ?, ?)",
            (new_parent.id, node.id, len(new_parent_children)),
        )
        await self.db._conn.commit()

        self.writer.schedule_writeback(file_id)
        logger.info("Indented node spec_ref=%s", spec_ref)

        updated = await self.db.get_node(node.id)
        assert updated is not None
        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=updated,
            tree_changed=True,
        )

    async def outdent_node(self, spec_ref: str) -> SpecUpdateResult:
        """Move the node up one level (heading level -1, becomes sibling of its parent).

        v1 constraint: same-file structural edits only.
        """
        await self.ensure_initialized()
        node = await self.db.get_node_by_ref(spec_ref)
        if node is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        raw = await self.db._one(
            "SELECT file_id, heading_level, sort_order FROM nodes WHERE id = ?",
            (node.id,),
        )
        if raw is None:
            raise SpecNotFoundError(f"no node found for spec_ref: {spec_ref}")

        heading_level = raw.get("heading_level")
        if heading_level is None:
            raise SpecValidationError(
                "outdent_node is only supported for heading nodes"
            )
        if heading_level <= 1:
            raise SpecValidationError(
                "cannot outdent: node is already at the top level"
            )

        file_id = int(raw["file_id"])

        parent_edge = await self.db._one(
            "SELECT parent_id FROM edges WHERE child_id = ?",
            (node.id,),
        )
        if parent_edge is None:
            raise SpecValidationError("cannot outdent: node has no parent")

        parent_id = parent_edge["parent_id"]
        parent_raw = await self.db._one(
            "SELECT file_id FROM nodes WHERE id = ?",
            (parent_id,),
        )
        if parent_raw is None:
            raise SpecServiceError("parent node not found")
        if int(parent_raw["file_id"]) != file_id:
            raise SpecValidationError("cross-file outdent is not supported in v1")

        # Grandparent determines where to re-attach.
        grand_edge = await self.db._one(
            "SELECT parent_id FROM edges WHERE child_id = ?",
            (parent_id,),
        )

        new_heading_level = heading_level - 1
        now = time.time()
        await self.db._execute(
            "UPDATE nodes SET heading_level = ?, depth = depth - 1, updated_at = ? WHERE id = ?",
            (new_heading_level, now, node.id),
        )

        # Recursively update all descendants: depth -1, heading_level -1 (if heading).
        descendants = await self.db.get_subtree(node.id)
        for desc in descendants:
            desc_raw = await self.db._one(
                "SELECT heading_level FROM nodes WHERE id = ?", (desc.id,)
            )
            if desc_raw and desc_raw["heading_level"] is not None:
                await self.db._execute(
                    "UPDATE nodes SET depth = depth - 1, heading_level = heading_level - 1, updated_at = ? WHERE id = ?",
                    (now, desc.id),
                )
            else:
                await self.db._execute(
                    "UPDATE nodes SET depth = depth - 1, updated_at = ? WHERE id = ?",
                    (now, desc.id),
                )

        # Remove old parent edge.
        await self.db._execute(
            "DELETE FROM edges WHERE child_id = ?",
            (node.id,),
        )

        # Attach to grandparent (or root) after the parent node.
        # Use proper edge sort_order insertion (shift siblings to make room).
        if grand_edge:
            grand_parent_id = grand_edge["parent_id"]
            grand_children = await self.db.get_children(grand_parent_id)
            parent_edge_row = await self.db._one(
                "SELECT sort_order FROM edges WHERE parent_id = ? AND child_id = ?",
                (grand_parent_id, parent_id),
            )
            parent_edge_sort = (
                int(parent_edge_row["sort_order"])
                if parent_edge_row
                else len(grand_children) - 1
            )
            # Shift all edges after parent's position to make room.
            await self.db._execute(
                "UPDATE edges SET sort_order = sort_order + 1 WHERE parent_id = ? AND sort_order > ?",
                (grand_parent_id, parent_edge_sort),
            )
            await self.db._execute(
                "INSERT OR IGNORE INTO edges(parent_id, child_id, sort_order) VALUES (?, ?, ?)",
                (grand_parent_id, node.id, parent_edge_sort + 1),
            )

        await self.db._conn.commit()
        self.writer.schedule_writeback(file_id)
        logger.info("Outdented node spec_ref=%s", spec_ref)

        updated = await self.db.get_node(node.id)
        assert updated is not None
        return SpecUpdateResult(
            previous_spec_ref=spec_ref,
            node=updated,
            tree_changed=True,
        )
