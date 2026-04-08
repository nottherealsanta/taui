from __future__ import annotations

import asyncio
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import time

from .db import SpecDB
from .markdown import markdown_first_line, strip_inline_metadata


class SpecMarkdownWriter:
    def __init__(self, *, workspace: Path, db: SpecDB, debounce_ms: int = 500) -> None:
        self.workspace = workspace
        self.db = db
        self.debounce_ms = debounce_ms
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._pending: set[int] = set()
        # When True, schedule_writeback() only marks the file dirty without
        # starting a debounced task. The caller is responsible for calling
        # flush_all_files() (or flush()) when it is ready to write.
        self._deferred: bool = False

    def schedule_writeback(self, file_id: int) -> None:
        self._pending.add(file_id)
        if self._deferred:
            # Deferred mode: don't start a background task; collect and batch.
            return
        task = self._tasks.get(file_id)
        if task is not None and not task.done():
            task.cancel()
        self._tasks[file_id] = asyncio.create_task(self._debounced_write(file_id))

    async def _debounced_write(self, file_id: int) -> None:
        try:
            await asyncio.sleep(self.debounce_ms / 1000)
            await self.write_file(file_id)
            self._pending.discard(file_id)
        except asyncio.CancelledError:
            return
        finally:
            if self._tasks.get(file_id) is asyncio.current_task():
                self._tasks.pop(file_id, None)

    async def write_file(self, file_id: int) -> None:
        file_row = await self.db.get_file_by_id(file_id)
        if file_row is None:
            return
        if getattr(file_row, "format", "legacy") == "standard":
            await self._write_file_standard(file_id, file_row)
            return
        nodes = await self.db.get_nodes_for_file(file_id)
        path = (self.workspace / file_row.rel_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []

        for idx, node in enumerate(nodes):
            heading_level = await self._node_heading_level(node.id)
            level = heading_level or 1
            indent = " " * max(0, (level - 1) * 4)
            markdown_lines = node.markdown.splitlines() if node.markdown else []
            first_line = markdown_lines[0].strip() if markdown_lines else ""
            lines.append(f"{indent}- {first_line}" if first_line else f"{indent}- ")

            continuation_lines = markdown_lines[1:] if len(markdown_lines) > 1 else []
            if continuation_lines:
                content_indent = " " * (max(0, (level - 1) * 4) + 4)
                lines.extend(
                    f"{content_indent}{line}" if line else ""
                    for line in continuation_lines
                )

            metadata_indent = " " * (max(0, (level - 1) * 4) + 4)
            if node.status:
                lines.append(f"{metadata_indent}- {{{{status: {node.status}}}}}")
            for code_ref in node.code_refs:
                lines.append(f"{metadata_indent}- {{{{code_ref: `{code_ref}`}}}}")
            if node.verification:
                lines.append(
                    f"{metadata_indent}- {{{{verification: {node.verification}}}}}"
                )

            depends_on = await self.db.get_depends_on(node.id)
            for target in depends_on:
                ref = self._format_node_ref(
                    current_file=file_row.rel_path, target=target
                )
                lines.append(f"{metadata_indent}- {{{{depends_on: {ref}}}}}")

            related = await self.db.get_related_to(node.id)
            for target in related:
                ref = self._format_node_ref(
                    current_file=file_row.rel_path, target=target
                )
                lines.append(f"{metadata_indent}- {{{{related_to: {ref}}}}}")

            cross_file_children = await self.db.get_cross_file_children(node.id)
            for child in cross_file_children:
                ref = self._format_tree_ref(
                    current_file=file_row.rel_path, target=child
                )
                lines.append(f"{metadata_indent}- {{{{tree: {ref}}}}}")

            if idx != len(nodes) - 1:
                lines.append("")

        text = "\n".join(lines).rstrip("\n")
        if text:
            text += "\n"
        path.write_text(text, encoding="utf-8")

        updated_hash = sha256(text.encode("utf-8")).hexdigest()
        mtime_ns = path.stat().st_mtime_ns
        await self.db.update_file_tracking(
            file_id,
            content_hash=updated_hash,
            mtime_ns=mtime_ns,
            last_seen=time.time(),
        )

    async def flush(self) -> None:
        pending = [task for task in self._tasks.values() if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._pending:
            for file_id in list(self._pending):
                await self.write_file(file_id)
                self._pending.discard(file_id)

    async def flush_all_files(self) -> None:
        """Write all dirty files immediately, cancelling any pending debounced tasks.

        Intended for use after an agent task completes so that all mutations
        accumulated during the task are flushed in one batch instead of many
        individual debounced writes.
        """
        # Cancel pending debounced tasks first
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        # Write everything that is still dirty
        for file_id in list(self._pending):
            await self.write_file(file_id)
            self._pending.discard(file_id)

    async def _write_file_standard(self, file_id: int, file_row: object) -> None:
        """Write a standard-format spec file (YAML frontmatter + markdown headings)."""
        rel_path: str = getattr(file_row, "rel_path")
        nodes = await self.db.get_nodes_for_file(file_id)
        path = (self.workspace / rel_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []

        root_node = nodes[0] if nodes else None

        # Build frontmatter from root node
        if root_node is not None:
            title = (
                root_node.markdown.splitlines()[0].strip().lstrip("#").strip()
                if root_node.markdown
                else ""
            )
            fm_lines: list[str] = ["---"]
            fm_lines.append(f"title: {title}" if title else "title: ''")
            fm_lines.append(f"status: {root_node.status or 'draft'}")
            fm_lines.append(
                f"last_updated: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}"
            )
            fm_lines.append("---")
            fm_lines.append("")
            lines.extend(fm_lines)

        for node in nodes:
            heading_level = node.line_start  # heading_level stored in nodes
            # Re-read actual heading level from DB
            row = await self.db._one(
                "SELECT heading_level FROM nodes WHERE id = ?", (node.id,)
            )
            level = (row.get("heading_level") if row else None) or 1
            hashes = "#" * level
            node_lines = node.markdown.splitlines() if node.markdown else [""]
            first = node_lines[0].strip().lstrip("#").strip()
            lines.append(f"{hashes} {first}")
            if len(node_lines) > 1:
                body = "\n".join(node_lines[1:]).strip("\n")
                if body:
                    lines.append("")
                    lines.append(body)
            lines.append("")

        text = "\n".join(lines).rstrip("\n")
        if text:
            text += "\n"
        path.write_text(text, encoding="utf-8")

        updated_hash = sha256(text.encode("utf-8")).hexdigest()
        mtime_ns = path.stat().st_mtime_ns
        await self.db.update_file_tracking(
            file_id,
            content_hash=updated_hash,
            mtime_ns=mtime_ns,
            last_seen=time.time(),
        )

    async def _node_heading_level(self, node_id: str) -> int | None:
        node = await self.db.get_node(node_id)
        if node is None or node.line_start is None:
            return None
        row = await self.db._one(
            "SELECT heading_level FROM nodes WHERE id = ?", (node_id,)
        )
        if row is None:
            return None
        return row.get("heading_level")

    def _format_node_ref(self, *, current_file: str, target: object) -> str:
        file_path = getattr(target, "file_path")
        anchor = getattr(target, "anchor")
        markdown = getattr(target, "markdown")

        current_path = Path(current_file)
        target_path = Path(file_path)
        relative_str = target_path.as_posix()
        try:
            relative_str = os.path.relpath(
                target_path.as_posix(), start=current_path.parent.as_posix()
            )
        except ValueError:
            relative_str = target_path.as_posix()

        title = strip_inline_metadata(markdown_first_line(markdown)).strip()
        title = title.lstrip("#").strip() or anchor.replace("-", " ")
        return f"[{title}]({relative_str}#{anchor})"

    def _format_tree_ref(self, *, current_file: str, target: object) -> str:
        """Format a {{tree: [Title](./path.md)}} link for cross-file expansion."""
        file_path = getattr(target, "file_path")
        markdown = getattr(target, "markdown")

        current_path = Path(current_file)
        target_path = Path(file_path)
        relative_str = target_path.as_posix()
        try:
            relative_str = os.path.relpath(
                target_path.as_posix(), start=current_path.parent.as_posix()
            )
        except ValueError:
            relative_str = target_path.as_posix()

        title = strip_inline_metadata(markdown_first_line(markdown)).strip()
        anchor = getattr(target, "anchor")
        title = title.lstrip("#").strip() or anchor.replace("-", " ")
        return f"[{title}]({relative_str})"


# Backward-compat alias for incremental migration
TangleMarkdownWriter = SpecMarkdownWriter
