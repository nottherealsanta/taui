"""Shared utilities for built-in tools — path safety, truncation, formatting."""

from __future__ import annotations

import difflib
from pathlib import Path

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
