"""Data models for the symbol index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SymbolEntry:
    """A symbol extracted from source code."""

    id: str
    name: str
    kind: str  # "function" | "class" | "variable" | "constant" | "import" | "type"
    file_path: str
    line_start: int  # 1-based
    line_end: int  # 1-based, inclusive
    scope: str  # "module" | "class:ClassName" | "function:func_name"
    parent_symbol: str | None = None
    language: str = "python"
    value_preview: str | None = None
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "scope": self.scope,
            "parent_symbol": self.parent_symbol,
            "language": self.language,
            "value_preview": self.value_preview,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SymbolEntry:
        return cls(
            id=d["id"],
            name=d["name"],
            kind=d["kind"],
            file_path=d["file_path"],
            line_start=d["line_start"],
            line_end=d["line_end"],
            scope=d["scope"],
            parent_symbol=d.get("parent_symbol"),
            language=d.get("language", "python"),
            value_preview=d.get("value_preview"),
            content_hash=d.get("content_hash", ""),
        )
