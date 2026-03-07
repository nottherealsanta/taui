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
    title: str
    depth: int
    file_path: str
    anchor: str
    intent: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec_ref": self.spec_ref,
            "title": self.title,
            "depth": self.depth,
            "file_path": self.file_path,
            "anchor": self.anchor,
            "intent": self.intent,
            "status": self.status,
        }


@dataclass(slots=True)
class SpecNodeDetail(SpecNode):
    content: str = ""
    line_start: int | None = None
    line_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = super(SpecNodeDetail, self).to_dict()
        out.update(
            {
                "content": self.content,
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
    title: str | None | object = UNSET
    intent: str | None | object = UNSET
    content: str | None | object = UNSET

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> "SpecNodePatch":
        allowed = {"title", "intent", "content"}
        extra = sorted(set(raw.keys()) - allowed)
        if extra:
            joined = ", ".join(extra)
            raise ValueError(f"unsupported patch fields: {joined}")

        kwargs: dict[str, object] = {}
        for key in ("title", "intent", "content"):
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
        return any(field is not UNSET for field in (self.title, self.intent, self.content))
