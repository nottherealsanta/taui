from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import time

from .db import SpecDB


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
        row = await self.db._one(
            "SELECT heading_level FROM nodes WHERE id = ?", (node_id,)
        )
        if row is None:
            return None
        return row.get("heading_level")
