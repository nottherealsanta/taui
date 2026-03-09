from __future__ import annotations

from dataclasses import dataclass
from typing import Any


UNSET = object()


@dataclass(slots=True)
class SpecFile:
    id: int
    rel_path: str
    content_hash: str
    last_seen: float
    mtime_ns: int


@dataclass(slots=True)
class SpecNode:
    id: str
    spec_ref: str
    depth: int
    file_path: str
    anchor: str
    markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec_ref": self.spec_ref,
            "depth": self.depth,
            "file_path": self.file_path,
            "anchor": self.anchor,
            "markdown": self.markdown,
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
