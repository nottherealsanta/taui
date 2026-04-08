"""MontyAPI — safe subset of taui APIs exposed to Monty scripts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class MontyAPI:
    """Limited API surface available inside Monty (sandboxed Python) scripts.

    Provides read-only file operations and workspace queries. No writes,
    no shell access, no network.
    """

    def __init__(self, working_dir: Path) -> None:
        self._root = working_dir.resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve a path relative to the workspace root, rejecting traversal."""
        resolved = (self._root / path).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise PermissionError(f"Path escapes workspace root: {path}")
        return resolved

    def read_file(self, path: str) -> str:
        """Read a text file from the workspace."""
        p = self._resolve(path)
        return p.read_text(encoding="utf-8", errors="replace")

    def file_exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def list_dir(self, path: str = ".") -> list[str]:
        """List entries in a directory (relative to workspace root)."""
        p = self._resolve(path)
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        entries: list[str] = []
        for entry in sorted(p.iterdir()):
            name = entry.name
            if entry.is_dir():
                name += "/"
            entries.append(name)
        return entries

    def glob(self, pattern: str) -> list[str]:
        """Glob files relative to workspace root."""
        matches: list[str] = []
        for p in sorted(self._root.glob(pattern)):
            try:
                rel = p.relative_to(self._root)
                matches.append(str(rel))
            except ValueError:
                continue
        return matches[:500]

    def workspace_root(self) -> str:
        return str(self._root)
