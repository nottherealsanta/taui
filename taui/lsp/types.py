"""LSP types used across the lsp module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Position:
    line: int  # 0-indexed
    character: int  # 0-indexed


@dataclass(slots=True)
class Range:
    start: Position
    end: Position


@dataclass(slots=True)
class Location:
    uri: str
    range: Range

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": _uri_to_path(self.uri),
            "line": self.range.start.line + 1,
            "character": self.range.start.character + 1,
            "end_line": self.range.end.line + 1,
            "end_character": self.range.end.character + 1,
        }


@dataclass(slots=True)
class Diagnostic:
    range: Range
    message: str
    severity: int = 1  # 1=Error 2=Warning 3=Info 4=Hint
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        sev_name = {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(
            self.severity, "unknown"
        )
        return {
            "line": self.range.start.line + 1,
            "character": self.range.start.character + 1,
            "severity": sev_name,
            "message": self.message,
            "source": self.source,
        }

    def pretty(self) -> str:
        sev = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}.get(
            self.severity, "???"
        )
        return (
            f"  L{self.range.start.line + 1}:{self.range.start.character + 1} "
            f"[{sev}] {self.message}"
        )


@dataclass(slots=True)
class SymbolInfo:
    name: str
    kind: int
    location: Location
    container_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        kind_name = _SYMBOL_KINDS.get(self.kind, f"kind_{self.kind}")
        d: dict[str, Any] = {
            "name": self.name,
            "kind": kind_name,
            **self.location.to_dict(),
        }
        if self.container_name:
            d["container"] = self.container_name
        return d


@dataclass(slots=True)
class HoverResult:
    contents: str
    range: Range | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"contents": self.contents}
        if self.range:
            d["line"] = self.range.start.line + 1
        return d


def _uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return uri


_SYMBOL_KINDS = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package",
    5: "Class", 6: "Method", 7: "Property", 8: "Field",
    9: "Constructor", 10: "Enum", 11: "Interface", 12: "Function",
    13: "Variable", 14: "Constant", 15: "String", 16: "Number",
    17: "Boolean", 18: "Array", 19: "Object", 20: "Key",
    21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}
