from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import re
import time

from .db import SpecDB

STATUS_RE = re.compile(r"\{\{status:\s*([a-zA-Z0-9_ -]+)\}\}")


class SpecMarkdownWriter:
    def __init__(self, *, workspace: Path, db: SpecDB, debounce_ms: int = 500) -> None:
        self.workspace = workspace
        self.db = db
        self.debounce_ms = debounce_ms
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._pending: set[int] = set()

    def schedule_writeback(self, file_id: int) -> None:
        self._pending.add(file_id)
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
        nodes = await self.db.get_nodes_for_file(file_id)
        path = (self.workspace / file_row.rel_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        if nodes and nodes[0].line_start is not None and nodes[0].line_start > 1 and nodes[0].content:
            # no special preface handling today; keeps parser-compatible output
            pass

        if nodes and nodes[0].line_start is not None and nodes[0].line_start > 0 and nodes[0].anchor:
            pass

        for idx, node in enumerate(nodes):
            if node.line_start is None:
                lines.append(node.title)
            else:
                # Plain-document nodes have no heading level in DB.
                heading_level = await self._node_heading_level(node.id)
                if heading_level is None:
                    lines.append(node.title)
                else:
                    lines.append(f"{'#' * heading_level} {node.title}")

            section_lines = node.content.splitlines() if node.content else []
            section_lines = self._inject_metadata(section_lines, node.id, node.status)
            if section_lines:
                lines.extend(section_lines)
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

    async def _node_heading_level(self, node_id: str) -> int | None:
        node = await self.db.get_node(node_id)
        if node is None or node.line_start is None:
            return None
        row = await self.db._one("SELECT heading_level FROM nodes WHERE id = ?", (node_id,))
        if row is None:
            return None
        return row.get("heading_level")

    async def _node_metadata_lines(self, node_id: str) -> list[str]:
        metadata = await self.db.get_node_metadata(node_id)
        out: list[str] = []
        for key, value in metadata:
            out.append(f"{{{{{key}: {value}}}}}")
        return out

    def _has_status(self, lines: list[str]) -> bool:
        scan_end = min(8, len(lines))
        for line in lines[:scan_end]:
            if STATUS_RE.search(line):
                return True
        return False

    def _has_metadata(self, lines: list[str], key: str) -> bool:
        needle = f"{{{{{key}:"
        scan_end = min(12, len(lines))
        for line in lines[:scan_end]:
            if needle in line:
                return True
        return False

    def _inject_status(self, lines: list[str], status: str | None) -> list[str]:
        if not status:
            return lines
        if self._has_status(lines):
            return lines
        return [f"{{{{status: {status}}}}}", *lines]

    def _inject_metadata(self, lines: list[str], node_id: str, status: str | None) -> list[str]:
        # status is always represented directly in-section for readability.
        out = self._inject_status(lines, status)
        return out
