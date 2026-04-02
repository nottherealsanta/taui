"""Box handoff — structured return from minion agents to parent.

Inspired by claw-code's structured handoff pattern: when a minion agent
completes its task, it packages its results into a ``Box`` — a structured
container with a summary, status, artifacts, and optional spec patches.

The parent agent receives the Box and can incorporate the results into
its own context without parsing free-form text.

Usage::

    box = Box(
        agent_id="minion-42",
        spec_ref="feature/auth",
        status=BoxStatus.COMPLETED,
        summary="Implemented JWT authentication with refresh tokens.",
        artifacts=[
            Artifact(path="src/auth.py", description="Auth module"),
        ],
    )
    parent_runner.receive_box(box)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BoxStatus(str, Enum):
    """Outcome status of a minion agent's work."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass(slots=True)
class Artifact:
    """A concrete output produced by the minion."""

    path: str  # file path or resource identifier
    description: str = ""
    artifact_type: str = "file"  # file | spec_patch | test_result | log

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "description": self.description,
            "type": self.artifact_type,
        }


@dataclass(slots=True)
class SpecPatch:
    """A proposed modification to a spec node."""

    spec_ref: str
    field: str  # "markdown" | "status" | "verification"
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_ref": self.spec_ref,
            "field": self.field,
            "value": self.value,
        }


@dataclass(slots=True)
class Box:
    """Structured handoff container from minion to parent agent.

    Encapsulates the results of a delegated task in a machine-readable
    format so the parent agent doesn't need to parse free-form text.
    """

    agent_id: str
    spec_ref: str
    status: BoxStatus
    summary: str
    artifacts: list[Artifact] = field(default_factory=list)
    spec_patches: list[SpecPatch] = field(default_factory=list)
    cost_usd: float = 0.0
    turn_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_success(self) -> bool:
        return self.status in (BoxStatus.COMPLETED, BoxStatus.PARTIAL)

    def to_message_content(self) -> str:
        """Format as a structured message for the parent agent's context."""
        lines = [
            f"## Minion Result: {self.spec_ref}",
            f"**Status**: {self.status.value}",
            f"**Agent**: {self.agent_id}",
            f"**Cost**: ${self.cost_usd:.4f} ({self.turn_count} turns)",
            "",
            f"### Summary",
            self.summary,
        ]

        if self.artifacts:
            lines.append("")
            lines.append("### Artifacts")
            for a in self.artifacts:
                lines.append(f"  - [{a.artifact_type}] `{a.path}`: {a.description}")

        if self.spec_patches:
            lines.append("")
            lines.append("### Spec Patches")
            for p in self.spec_patches:
                lines.append(f"  - `{p.spec_ref}`.{p.field} = {p.value[:100]}")

        if self.error:
            lines.append("")
            lines.append(f"### Error\n{self.error}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "spec_ref": self.spec_ref,
            "status": self.status.value,
            "summary": self.summary,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "spec_patches": [p.to_dict() for p in self.spec_patches],
            "cost_usd": round(self.cost_usd, 6),
            "turn_count": self.turn_count,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Box":
        return cls(
            agent_id=data["agent_id"],
            spec_ref=data["spec_ref"],
            status=BoxStatus(data["status"]),
            summary=data["summary"],
            artifacts=[
                Artifact(
                    path=a["path"],
                    description=a.get("description", ""),
                    artifact_type=a.get("type", "file"),
                )
                for a in data.get("artifacts", [])
            ],
            spec_patches=[
                SpecPatch(
                    spec_ref=p["spec_ref"],
                    field=p["field"],
                    value=p["value"],
                )
                for p in data.get("spec_patches", [])
            ],
            cost_usd=data.get("cost_usd", 0.0),
            turn_count=data.get("turn_count", 0),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )
