"""Data models for semantic references and symbol entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SemanticRef:
    """A reference from a spec node to a code artifact."""

    file_path: str
    symbol_path: str | None = None
    ref_kind: str = "symbol_ref"  # "line_ref" | "symbol_ref" | "variable_ref" | "file_ref"
    language: str | None = None
    edit_policy: str | None = None  # "replace_literal" | "replace_property" | "replace_enum" | None
    line_start: int | None = None  # Derived resolution data
    line_end: int | None = None  # Derived resolution data

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "symbol_path": self.symbol_path,
            "ref_kind": self.ref_kind,
            "language": self.language,
            "edit_policy": self.edit_policy,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SemanticRef:
        return cls(
            file_path=d["file_path"],
            symbol_path=d.get("symbol_path"),
            ref_kind=d.get("ref_kind", "symbol_ref"),
            language=d.get("language"),
            edit_policy=d.get("edit_policy"),
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
        )


@dataclass(slots=True)
class ResolvedRef:
    """Result of resolving a SemanticRef to a concrete code location."""

    file_path: str
    line_start: int
    line_end: int
    column_start: int | None = None
    column_end: int | None = None
    preview_snippet: str = ""
    symbol_kind: str | None = None
    symbol_metadata: dict[str, Any] = field(default_factory=dict)
    writable: bool = False
    edit_strategy: str | None = None
    confidence: str = "high"  # "high" | "medium" | "low"
    fallback_reason: str | None = None
    diagnostic: str = "resolved"  # "resolved" | "resolved_warning" | "unresolved" | "stale" | "ambiguous"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
            "preview_snippet": self.preview_snippet,
            "symbol_kind": self.symbol_kind,
            "symbol_metadata": self.symbol_metadata,
            "writable": self.writable,
            "edit_strategy": self.edit_strategy,
            "confidence": self.confidence,
            "fallback_reason": self.fallback_reason,
            "diagnostic": self.diagnostic,
        }


@dataclass(slots=True)
class SymbolEntry:
    """A symbol extracted from source code by the tree-sitter indexer."""

    id: str
    name: str
    kind: str  # "function" | "class" | "variable" | "constant" | "import" | "css_property" | "type"
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
