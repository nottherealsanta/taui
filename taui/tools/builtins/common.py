"""Shared utilities for built-in tools — path safety, truncation, formatting."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Directories to skip during recursive operations
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".egg-info",
})


def resolve_path(working_dir: Path, raw: str) -> Path:
    """Resolve a path relative to working_dir. Rejects escapes."""
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = working_dir / p
    p = p.resolve()
    wd = working_dir.resolve()
    try:
        p.relative_to(wd)
    except ValueError:
        raise ValueError(
            f"Path {str(p)!r} is outside the workspace {str(wd)!r}"
        ) from None
    return p


def is_binary(path: Path, sample_size: int = 8192) -> bool:
    """Quick heuristic: null bytes or high ratio of non-printable chars."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
        if b"\x00" in chunk:
            return True
        if not chunk:
            return False
        # >30% non-printable = likely binary
        non_printable = sum(
            1 for b in chunk if b < 0x20 and b not in (0x09, 0x0A, 0x0D)
        )
        return non_printable / len(chunk) > 0.3
    except OSError:
        return True


def suggest_similar(path: Path, working_dir: Path, n: int = 5) -> str | None:
    """Suggest similar filenames when a file is not found."""
    parent = path.parent
    if not parent.is_dir():
        return None
    try:
        siblings = [p.name for p in parent.iterdir()]
    except PermissionError:
        return None
    matches = difflib.get_close_matches(path.name, siblings, n=n, cutoff=0.5)
    if not matches:
        return None
    suggestions = [str(parent / m) for m in matches]
    try:
        suggestions = [
            str(Path(s).relative_to(working_dir)) for s in suggestions
        ]
    except ValueError:
        pass
    return "Did you mean: " + ", ".join(suggestions) + "?"


def truncate(
    text: str, *, max_lines: int = 2000, max_bytes: int = 50_000
) -> tuple[str, bool]:
    """Truncate text to fit within limits. Returns (text, was_truncated).

    Respects both line count and byte budget. Never splits a line.
    """
    lines = text.splitlines(keepends=True)
    result_lines: list[str] = []
    byte_count = 0
    truncated = False

    for line in lines:
        line_bytes = len(line.encode("utf-8", errors="replace"))
        if len(result_lines) >= max_lines or byte_count + line_bytes > max_bytes:
            truncated = True
            break
        result_lines.append(line)
        byte_count += line_bytes

    result = "".join(result_lines)
    if truncated:
        remaining = len(lines) - len(result_lines)
        result += f"\n\n… ({remaining} more lines truncated)"
    return result, truncated


# ── Truncation envelope ───────────────────────────────────────────────────────


@dataclass(slots=True)
class TruncationEnvelope:
    """Structured info about a partial-data tool result.

    Tools that hit a size or count limit return this so the agent knows it has
    incomplete data — and how to ask for the rest (via `peek_handle` when the
    full content was preserved, otherwise just by re-running with narrower
    arguments).
    """

    truncated_at: int           # what we cut at — bytes, matches, lines, etc.
    unit: str                   # "bytes", "lines", "matches", "files"
    total_hint: int | None = None   # full count when known
    peek_handle: str | None = None  # handle into TruncationStore, when stored
    next_hint: str | None = None    # human hint for how to fetch more

    def format_footer(self) -> str:
        if self.total_hint is not None and self.total_hint > self.truncated_at:
            shown = (
                f"showing {self.truncated_at} of {self.total_hint} {self.unit}"
            )
        else:
            shown = f"showing first {self.truncated_at} {self.unit}; total unknown"
        parts = [f"[truncated: {shown}"]
        if self.peek_handle:
            parts.append(
                f'; peek(handle="{self.peek_handle}") to read full output'
            )
        if self.next_hint:
            parts.append(f"; {self.next_hint}")
        parts.append("]")
        return "\n\n" + "".join(parts)

    def to_metadata(self) -> dict[str, Any]:
        """Render as a metadata sub-dict the agent / UI can introspect."""
        out: dict[str, Any] = {
            "truncated": True,
            "truncated_at": self.truncated_at,
            "unit": self.unit,
        }
        if self.total_hint is not None:
            out["total_hint"] = self.total_hint
        if self.peek_handle:
            out["peek_handle"] = self.peek_handle
        if self.next_hint:
            out["next_hint"] = self.next_hint
        return out
