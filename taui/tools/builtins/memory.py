"""Memory tool — persistent cross-session knowledge storage.

Stores knowledge as plain text files in `.taui/memory/` within the
workspace. The agent can save, read, list, and delete memory entries
to retain knowledge across sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class MemoryTool:
    """Read and write persistent memory entries.

    Memory is stored as files in `.taui/memory/` in the workspace directory.
    Each entry has a key (filename) and content (file contents).
    """

    name: str = "memory"
    description: str = (
        "Manage persistent memory entries that survive across sessions. "
        "Operations: save (create/overwrite), read, list, delete. "
        "Use memory to store important context, decisions, patterns, "
        "and project knowledge."
    )
    category: ToolCategory = ToolCategory.MEMORY
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `memory` to persist important discoveries, decisions, and patterns. "
        "Good candidates: project conventions, build commands, architecture notes, "
        "user preferences. Keep entries focused and concise. "
        "List existing entries before creating new ones to avoid duplicates."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["save", "read", "list", "delete"],
                        "description": "Operation: save (create/overwrite), read, list, delete.",
                    },
                    "key": {
                        "type": "string",
                        "description": (
                            "Memory entry key (filename without extension). "
                            "e.g. 'build-commands', 'architecture-notes'"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to save (for 'save' operation).",
                    },
                },
                "required": ["operation"],
            }

    @property
    def _memory_dir(self) -> Path:
        return self.working_dir / ".taui" / "memory"

    def _resolve_key(self, key: str) -> Path:
        """Resolve key to a file path, preventing path traversal."""
        # Sanitize: only allow simple filenames
        safe = key.replace("/", "_").replace("\\", "_").replace("..", "_")
        if not safe or safe.startswith("."):
            safe = "_" + safe
        path = (self._memory_dir / safe).with_suffix(".md")
        # Verify it's within the memory directory. Use a real path-containment
        # check rather than a string prefix (which would treat a sibling like
        # `<dir>-evil` as inside).
        if not path.resolve().is_relative_to(self._memory_dir.resolve()):
            raise ValueError("Invalid key: path traversal detected")
        return path

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation")
        if not isinstance(op, str):
            return ToolResult.fail("'operation' is required (save, read, list, delete).")

        match op:
            case "save":
                return await self._save(arguments)
            case "read":
                return await self._read(arguments)
            case "list":
                return await self._list()
            case "delete":
                return await self._delete(arguments)
            case _:
                return ToolResult.fail(
                    f"Unknown operation '{op}'. Use: save, read, list, delete."
                )

    async def _save(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments.get("key")
        content = arguments.get("content")
        if not isinstance(key, str) or not key.strip():
            return ToolResult.fail("'key' is required for save.")
        if not isinstance(content, str):
            return ToolResult.fail("'content' is required for save.")

        try:
            path = self._resolve_key(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult.ok(f"Saved memory entry '{key}'.", key=key)
        except Exception as exc:
            return ToolResult.fail(f"Failed to save: {exc}")

    async def _read(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments.get("key")
        if not isinstance(key, str) or not key.strip():
            return ToolResult.fail("'key' is required for read.")

        try:
            path = self._resolve_key(key)
            if not path.exists():
                # Suggest similar entries
                existing = self._list_keys()
                msg = f"Memory entry '{key}' not found."
                if existing:
                    msg += f" Available: {', '.join(existing)}"
                return ToolResult.fail(msg)
            content = path.read_text(encoding="utf-8")
            return ToolResult.ok(content, key=key)
        except Exception as exc:
            return ToolResult.fail(f"Failed to read: {exc}")

    async def _list(self) -> ToolResult:
        entries = self._list_keys()
        if not entries:
            return ToolResult.ok("No memory entries found.")
        lines = [f"Memory entries ({len(entries)}):"]
        for key in entries:
            path = self._resolve_key(key)
            size = path.stat().st_size
            lines.append(f"  - {key} ({size} bytes)")
        return ToolResult.ok("\n".join(lines), count=len(entries))

    async def _delete(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments.get("key")
        if not isinstance(key, str) or not key.strip():
            return ToolResult.fail("'key' is required for delete.")

        try:
            path = self._resolve_key(key)
            if not path.exists():
                return ToolResult.fail(f"Memory entry '{key}' not found.")
            path.unlink()
            return ToolResult.ok(f"Deleted memory entry '{key}'.", key=key)
        except Exception as exc:
            return ToolResult.fail(f"Failed to delete: {exc}")

    def _list_keys(self) -> list[str]:
        """List all memory entry keys."""
        if not self._memory_dir.exists():
            return []
        return sorted(p.stem for p in self._memory_dir.glob("*.md"))
