from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


UNSET = object()


@dataclass(slots=True)
class SpecFile:
    id: int
    rel_path: str
    content_hash: str
    last_seen: float
    mtime_ns: int
    format: str = "legacy"


@dataclass(slots=True)
class SpecNode:
    id: str
    spec_ref: str
    depth: int
    file_path: str
    anchor: str
    markdown: str = ""
    status: str | None = None
    code_refs: list[str] = field(default_factory=list)
    verification: str | None = None
    collapsed: bool = False
    depends_on: list[str] = field(default_factory=list)
    related_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec_ref": self.spec_ref,
            "depth": self.depth,
            "file_path": self.file_path,
            "anchor": self.anchor,
            "markdown": self.markdown,
            "status": self.status,
            "code_refs": self.code_refs,
            "verification": self.verification,
            "collapsed": self.collapsed,
            "depends_on": self.depends_on,
            "related_to": self.related_to,
        }


@dataclass(slots=True)
class SpecNodeDetail(SpecNode):
    line_start: int | None = None
    line_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = super(SpecNodeDetail, self).to_dict()
        out.update(
            {
                "line_start": self.line_start,
                "line_end": self.line_end,
            }
        )
        return out


@dataclass(slots=True)
class SpecUpdateResult:
    previous_spec_ref: str
    node: SpecNodeDetail
    tree_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_spec_ref": self.previous_spec_ref,
            "node": self.node.to_dict(),
            "tree_changed": self.tree_changed,
        }


@dataclass(slots=True)
class SpecNodePatch:
    markdown: str | None | object = UNSET

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> "SpecNodePatch":
        allowed = {"markdown"}
        extra = sorted(set(raw.keys()) - allowed)
        if extra:
            joined = ", ".join(extra)
            raise ValueError(f"unsupported patch fields: {joined}")

        kwargs: dict[str, object] = {}
        for key in ("markdown",):
            if key not in raw:
                continue
            value = raw[key]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"patch field '{key}' must be a string or null")
            kwargs[key] = value

        patch = cls(**kwargs)
        if not patch.has_changes:
            raise ValueError("patch must include at least one field")
        return patch

    @property
    def has_changes(self) -> bool:
        return self.markdown is not UNSET


@dataclass(slots=True)
class TangleFileMeta:
    id: int
    rel_path: str
    content_hash: str
    mtime_ns: int
    title: str
    last_updated: str
    last_seen: float


@dataclass(slots=True)
class TangleRef:
    file_path: str
    target: str
    context: str
    line_in_tangle: int


@dataclass(slots=True)
class TangleLink:
    source_path: str
    target_path: str
    link_type: str


@dataclass(slots=True)
class TangleCodeBlock:
    """A ::code directive embedding source code from another file.

    Format: ::code file_path:symbol_name or ::code file_path:start-end

    The code block is rendered as an editable code window in the tangle editor.
    Edits are written back to the original source file.
    """

    file_path: str
    target: str  # symbol name or "start-end" line range
    line_in_tangle: int  # 1-based line number in the tangle document
    ref_kind: str = "symbol"  # "symbol" or "lines"

    # Resolved fields (populated after resolution)
    resolved_start: int | None = None  # 1-based line in source file
    resolved_end: int | None = None  # 1-based line in source file
    content: str | None = None  # The actual source code
    language: str | None = None  # Language for syntax highlighting
    diagnostic: str = "pending"  # "resolved" | "unresolved" | "stale"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "target": self.target,
            "line_in_tangle": self.line_in_tangle,
            "ref_kind": self.ref_kind,
            "resolved_start": self.resolved_start,
            "resolved_end": self.resolved_end,
            "content": self.content,
            "language": self.language,
            "diagnostic": self.diagnostic,
        }


@dataclass(slots=True)
class TangleNode:
    id: str
    tangle_path: str
    heading: str
    depth: int
    anchor: str
    body: str
    refs: list[TangleRef]
    line_start: int
    line_end: int


@dataclass(slots=True)
class TangleDetail:
    file: TangleFileMeta
    nodes: list[TangleNode]
    refs: list[TangleRef]
    links: list[TangleLink]
    code_blocks: list[TangleCodeBlock]
    frontmatter: dict[str, Any]


# Backward-compat aliases for incremental migration
LegacyTangleFile = SpecFile
LegacyTangleNode = SpecNode
LegacyTangleNodeDetail = SpecNodeDetail
LegacyTangleUpdateResult = SpecUpdateResult
LegacyTangleNodePatch = SpecNodePatch
