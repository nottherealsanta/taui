"""Fast file/folder scanner for the chat input's `@` autocomplete.

Walks the working directory once, caches the result, and ranks against the
typed prefix on each keystroke. The walk excludes common large/uninteresting
directories so it stays snappy on real projects.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# Directory names to skip during the walk. Hidden directories (leading `.`)
# are also skipped except for the project root itself.
_SKIP_DIRS = frozenset({
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "env",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".idea",
    ".vscode",
    ".next",
    ".turbo",
    ".cache",
    "coverage",
    "__snapshots__",
})

_MAX_ENTRIES = 20_000
_CACHE_TTL = 5.0  # seconds


class AtCompleter:
    """Cached file/folder index for `@` completion.

    One instance per working directory. ``complete(prefix)`` returns ranked
    relative paths (files + folders) matching ``prefix`` — fastest when called
    repeatedly with growing prefixes, since the directory walk is cached.
    """

    __slots__ = ("_root", "_entries", "_built_at")

    def __init__(self, root: Path) -> None:
        self._root: Path = root
        self._entries: list[tuple[str, str, bool]] = []  # (relpath, lower, is_dir)
        self._built_at: float = 0.0

    def invalidate(self) -> None:
        self._built_at = 0.0

    def _ensure_fresh(self) -> None:
        now = time.monotonic()
        if self._entries and (now - self._built_at) < _CACHE_TTL:
            return
        self._entries = _walk(self._root)
        self._built_at = now

    def complete(
        self,
        prefix: str,
        *,
        limit: int = 30,
    ) -> list[tuple[str, bool]]:
        """Return up to *limit* matching ``(relpath, is_dir)`` pairs."""
        self._ensure_fresh()
        entries = self._entries
        if not prefix:
            # No prefix — return the first *limit* directories then files,
            # alphabetically, so the dropdown is meaningful before any typing.
            head: list[tuple[str, bool]] = []
            for rel, _low, is_dir in entries:
                if "/" in rel:
                    continue  # top-level only when empty prefix
                head.append((rel, is_dir))
                if len(head) >= limit:
                    break
            return head

        p = prefix.lower()
        # Three buckets ranked by match quality.
        exact_path: list[tuple[str, bool]] = []
        exact_name: list[tuple[str, bool]] = []
        substr: list[tuple[str, bool]] = []

        for rel, low, is_dir in entries:
            if low.startswith(p):
                exact_path.append((rel, is_dir))
                if len(exact_path) >= limit:
                    break
                continue
            # name-only prefix match
            slash = low.rfind("/")
            name = low[slash + 1:] if slash >= 0 else low
            if name.startswith(p):
                if len(exact_name) < limit:
                    exact_name.append((rel, is_dir))
                continue
            if p in low:
                if len(substr) < limit:
                    substr.append((rel, is_dir))

        merged = exact_path + exact_name + substr
        return merged[:limit]


def _walk(root: Path) -> list[tuple[str, str, bool]]:
    """Walk *root* once, returning ``(relpath, lower_relpath, is_dir)`` entries.

    The relative path uses forward slashes regardless of OS, both to keep the
    dropdown display stable and because path queries are typed with `/`.
    """
    out: list[tuple[str, str, bool]] = []
    root_str = str(root)
    root_len = len(root_str) + 1  # +1 for separator

    try:
        for dirpath, dirnames, filenames in os.walk(root_str, followlinks=False):
            # Filter in-place so os.walk doesn't recurse into skipped dirs.
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            base = dirpath[root_len:] if len(dirpath) >= root_len else ""
            for d in dirnames:
                rel = f"{base}/{d}" if base else d
                rel = rel.replace(os.sep, "/")
                out.append((rel, rel.lower(), True))
            for f in filenames:
                if f.startswith("."):
                    continue
                rel = f"{base}/{f}" if base else f
                rel = rel.replace(os.sep, "/")
                out.append((rel, rel.lower(), False))
            if len(out) >= _MAX_ENTRIES:
                return out
    except OSError:
        return out
    return out
