"""File operation tools — read, write, glob, grep."""

from __future__ import annotations

import fnmatch
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import (
    SKIP_DIRS,
    is_binary,
    resolve_path,
    suggest_similar,
)

_MAX_LINE_CHARS = 2000


# ── ReadTool ──────────────────────────────────────────────────────────────────


@dataclass
class ReadTool:
    """Read a file's contents or list a directory."""

    name: str = "read"
    description: str = (
        "Read the contents of a file, or list the entries in a directory. "
        "For files, returns numbered lines. For directories, returns the listing."
    )
    category: ToolCategory = ToolCategory.FILE_READ
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `read` before editing a file — never edit blind. "
        "For large files, use `offset` and `limit` to page through. "
        "Reading a directory first helps discover file structure."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to read.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start from (1-indexed). Default: 1.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return. Default: 500.",
                    },
                },
                "required": ["path"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = resolve_path(self.working_dir, arguments["path"])
        except ValueError as e:
            return ToolResult.fail(str(e))

        if not path.exists():
            hint = suggest_similar(path, self.working_dir)
            msg = f"Path not found: {path}"
            if hint:
                msg += f"\n{hint}"
            return ToolResult.fail(msg)

        if path.is_dir():
            return self._read_dir(path)

        return self._read_file(path, arguments)

    def _read_dir(self, path: Path) -> ToolResult:
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return ToolResult.fail(f"Permission denied: {path}")

        lines = []
        for entry in entries:
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{entry.name}{suffix}")
        return ToolResult.ok("\n".join(lines) if lines else "(empty directory)")

    def _read_file(self, path: Path, arguments: dict[str, Any]) -> ToolResult:
        if is_binary(path):
            return ToolResult.fail(f"Binary file, cannot display: {path}")

        offset = max(1, arguments.get("offset", 1))
        limit = min(2000, arguments.get("limit", 500))

        try:
            all_lines = path.read_text(errors="replace").splitlines(keepends=True)
        except PermissionError:
            return ToolResult.fail(f"Permission denied: {path}")
        except OSError as e:
            return ToolResult.fail(f"Error reading {path}: {e}")

        total = len(all_lines)
        selected = all_lines[offset - 1 : offset - 1 + limit]

        numbered: list[str] = []
        for i, line in enumerate(selected, start=offset):
            text = line.rstrip("\n\r")
            if len(text) > _MAX_LINE_CHARS:
                text = text[:_MAX_LINE_CHARS] + "…"
            numbered.append(f"{i:5d}| {text}")

        result = "\n".join(numbered)

        remaining = total - (offset - 1 + len(selected))
        if remaining > 0:
            result += f"\n\n({remaining} more lines. Use offset={offset + limit} to continue.)"

        return ToolResult.ok(result, total_lines=total, path=str(path))


# ── WriteTool ─────────────────────────────────────────────────────────────────


@dataclass
class WriteTool:
    """Write content to a file. Creates parent directories as needed."""

    name: str = "write"
    description: str = (
        "Write content to a file. Creates the file and parent directories "
        "if they don't exist. Overwrites existing content."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `write` for creating new files or replacing entire file contents. "
        "For targeted changes to existing files, prefer `edit` instead."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = resolve_path(self.working_dir, arguments["path"])
        except ValueError as e:
            return ToolResult.fail(str(e))

        content = arguments.get("content", "")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write: temp file then rename
            fd, tmp = tempfile.mkstemp(
                dir=path.parent, suffix=".tmp", prefix=".taui_write_"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                Path(tmp).replace(path)
            except Exception:
                Path(tmp).unlink(missing_ok=True)
                raise
        except PermissionError:
            return ToolResult.fail(f"Permission denied: {path}")
        except OSError as e:
            return ToolResult.fail(f"Error writing {path}: {e}")

        lines = content.count("\n") + (
            1 if content and not content.endswith("\n") else 0
        )
        return ToolResult.ok(
            f"Wrote {lines} lines to {path}", path=str(path), lines=lines
        )


# ── GlobTool ──────────────────────────────────────────────────────────────────


@dataclass
class GlobTool:
    """Find files matching a glob pattern."""

    name: str = "glob"
    description: str = (
        "Find files matching a glob pattern. "
        "Returns paths sorted by modification time (newest first)."
    )
    category: ToolCategory = ToolCategory.SEARCH
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use glob to discover files by extension or name pattern. "
        "Common patterns: '**/*.py', 'src/**/*.ts', '**/test_*.py'."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
                    },
                    "path": {
                        "type": "string",
                        "description": "Base directory to search from. Default: working directory.",
                    },
                },
                "required": ["pattern"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        base_raw = arguments.get("path", ".")
        try:
            base = resolve_path(self.working_dir, base_raw)
        except ValueError as e:
            return ToolResult.fail(str(e))

        if not base.is_dir():
            return ToolResult.fail(f"Not a directory: {base}")

        pattern = arguments["pattern"]
        try:
            matches = [
                p
                for p in base.glob(pattern)
                if not any(part in SKIP_DIRS for part in p.parts)
            ]
        except (ValueError, OSError) as e:
            return ToolResult.fail(f"Glob error: {e}")

        # Sort by mtime, newest first
        matches.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        if not matches:
            return ToolResult.ok(f"No matches for pattern {pattern!r} in {base}")

        lines = [str(p.relative_to(self.working_dir)) for p in matches[:200]]
        result = "\n".join(lines)
        if len(matches) > 200:
            result += f"\n\n({len(matches) - 200} more matches not shown)"

        return ToolResult.ok(result, count=len(matches), pattern=pattern)


# ── GrepTool ──────────────────────────────────────────────────────────────────


@dataclass
class GrepTool:
    """Search file contents with a regex pattern."""

    name: str = "grep"
    description: str = (
        "Search for a regex pattern across files. "
        "Returns matching lines with file paths and line numbers."
    )
    category: ToolCategory = ToolCategory.SEARCH
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use grep to find where something is defined or used. "
        "Use `include` to limit to specific file types (e.g. '*.py')."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Base directory to search. Default: working directory.",
                    },
                    "include": {
                        "type": "string",
                        "description": "Filename glob filter (e.g. '*.py'). Default: all files.",
                    },
                },
                "required": ["pattern"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        base_raw = arguments.get("path", ".")
        try:
            base = resolve_path(self.working_dir, base_raw)
        except ValueError as e:
            return ToolResult.fail(str(e))

        if not base.is_dir():
            return ToolResult.fail(f"Not a directory: {base}")

        try:
            regex = re.compile(arguments["pattern"])
        except re.error as e:
            return ToolResult.fail(f"Invalid regex: {e}")

        include = arguments.get("include")
        matches: list[str] = []
        files_matched: set[str] = set()
        max_matches = 500

        for filepath in sorted(base.rglob("*")):
            if not filepath.is_file():
                continue
            if any(part in SKIP_DIRS for part in filepath.parts):
                continue
            if include and not fnmatch.fnmatch(filepath.name, include):
                continue
            if is_binary(filepath):
                continue

            try:
                text = filepath.read_text(errors="replace")
            except (OSError, PermissionError):
                continue

            rel = str(filepath.relative_to(self.working_dir))
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    display = line.strip()
                    if len(display) > 200:
                        display = display[:200] + "…"
                    matches.append(f"{rel}:{lineno}| {display}")
                    files_matched.add(rel)
                    if len(matches) >= max_matches:
                        break
            if len(matches) >= max_matches:
                break

        if not matches:
            return ToolResult.ok(
                f"No matches for /{arguments['pattern']}/ in {base}",
                match_count=0,
            )

        result = "\n".join(matches)
        if len(matches) >= max_matches:
            result += f"\n\n(truncated at {max_matches} matches)"

        return ToolResult.ok(
            result,
            match_count=len(matches),
            file_count=len(files_matched),
        )
