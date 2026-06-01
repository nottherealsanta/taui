"""File operation tools — read, write, glob, grep."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import (
    SKIP_DIRS,
    TruncationEnvelope,
    is_binary,
    resolve_path,
    suggest_similar,
)
from taui.tools.file_tracker import FileTracker

_MAX_LINE_CHARS = 2000

# ── ripgrep detection (cached) ────────────────────────────────────────────────

_rg_path: str | None | bool = False  # False = not yet checked


def _get_rg() -> str | None:
    """Return the path to ``rg`` if available, else ``None``.  Cached."""
    global _rg_path
    if _rg_path is False:
        _rg_path = shutil.which("rg")
    return _rg_path  # type: ignore[return-value]


# Wall-clock timeout for subprocesses and the Python fallback search.
_SEARCH_TIMEOUT_SECS = 15

# Regex to parse rg output lines: path:lineno:content
# Uses non-greedy match on path to handle Windows drive letters (e.g. C:\path:10:content)
_RG_LINE_RE = re.compile(r'^(.+?):(\d+):(.*)$')

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
    _file_tracker: FileTracker | None = None
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

        result = self._read_file(path, arguments)
        if not result.error and self._file_tracker is not None:
            self._file_tracker.record_read(path)
        return result

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
    requires_approval: bool = True
    working_dir: Path = field(default_factory=Path.cwd)
    _path_guard: Any = None
    _file_tracker: FileTracker | None = None
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

        if self._path_guard:
            guard_result = self._path_guard(path)
            if guard_result is not None:
                return guard_result

        if self._file_tracker is not None:
            tracker_error = self._file_tracker.check_before_write(path)
            if tracker_error is not None:
                return ToolResult.fail(tracker_error)

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
        if self._file_tracker is not None:
            self._file_tracker.update_after_write(path)
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
    _truncation_store: Any = field(default=None, repr=False)
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

        # Try ripgrep first (respects .gitignore)
        rg = _get_rg()
        if rg is not None:
            return await self._glob_rg(rg, base, pattern)

        # Fallback to Python
        return self._glob_python(base, pattern)

    async def _glob_rg(self, rg: str, base: Path, pattern: str) -> ToolResult:
        """Use ``rg --files`` with a glob filter — .gitignore-aware."""
        cmd = [rg, "--files", "-g", pattern, "--", str(base)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=_SEARCH_TIMEOUT_SECS
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult.fail(
                    "glob search timed out; narrow the pattern or add a `path`."
                )
        except FileNotFoundError:
            # rg vanished between detection and invocation — fall through
            return self._glob_python(base, pattern)

        raw_paths = stdout.decode("utf-8", errors="replace").splitlines()
        if not raw_paths or (len(raw_paths) == 1 and not raw_paths[0].strip()):
            return ToolResult.ok(f"No matches for pattern {pattern!r} in {base}")

        # Resolve to Path objects for mtime sorting
        path_objs: list[Path] = []
        for rp in raw_paths:
            rp = rp.strip()
            if not rp:
                continue
            p = Path(rp)
            if not p.is_absolute():
                p = self.working_dir / p
            path_objs.append(p)

        # Sort by mtime, newest first
        path_objs.sort(
            key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True
        )

        return self._format_glob_result(path_objs, pattern)

    def _glob_python(self, base: Path, pattern: str) -> ToolResult:
        """Pure-Python fallback (no .gitignore awareness)."""
        try:
            matches = [
                p
                for p in base.glob(pattern)
                if not any(part in SKIP_DIRS for part in p.parts)
            ]
        except (ValueError, OSError) as e:
            return ToolResult.fail(f"Glob error: {e}")

        matches.sort(
            key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True
        )

        if not matches:
            return ToolResult.ok(f"No matches for pattern {pattern!r} in {base}")

        return self._format_glob_result(matches, pattern)

    def _format_glob_result(
        self, matches: list[Path], pattern: str
    ) -> ToolResult:
        max_shown = 200
        all_lines = [str(p.relative_to(self.working_dir)) for p in matches]
        shown_lines = all_lines[:max_shown]
        result = "\n".join(shown_lines)
        meta: dict[str, Any] = {"count": len(matches), "pattern": pattern}

        if len(matches) > max_shown:
            handle: str | None = None
            if self._truncation_store is not None:
                handle = self._truncation_store.store(
                    "\n".join(all_lines), tool_name="glob"
                )
            envelope = TruncationEnvelope(
                truncated_at=max_shown,
                unit="files",
                total_hint=len(matches),
                peek_handle=handle,
                next_hint="narrow the pattern or add a `path` to focus the search",
            )
            result += envelope.format_footer()
            meta.update(envelope.to_metadata())

        return ToolResult.ok(result, **meta)


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
    _truncation_store: Any = field(default=None, repr=False)
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

        single_file = False
        if base.is_file():
            single_file = True
        elif not base.is_dir():
            return ToolResult.fail(f"Path not found: {base}")

        pattern = arguments["pattern"]
        include = arguments.get("include")

        # Try ripgrep first (respects .gitignore, immune to ReDoS)
        rg = _get_rg()
        if rg is not None and not single_file:
            return await self._grep_rg(rg, base, pattern, include)

        # Fallback to Python (single files always use Python, or when rg absent)
        return self._grep_python(base, pattern, include, single_file)

    async def _grep_rg(
        self,
        rg: str,
        base: Path,
        pattern: str,
        include: str | None,
    ) -> ToolResult:
        """Use ``rg`` for .gitignore-aware, ReDoS-immune search."""
        max_matches = 500
        overflow_cap = max_matches * 4

        # Build command: rg --line-number --no-heading --color never [-g include] -e pattern -- base
        cmd: list[str] = [
            rg,
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--max-count",
            str(overflow_cap),
        ]
        if include:
            cmd.extend(["-g", include])
        cmd.extend(["-e", pattern, "--", str(base)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_SEARCH_TIMEOUT_SECS
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult.fail(
                    "grep search timed out; narrow the pattern or add `include`."
                )
        except FileNotFoundError:
            # rg vanished — fall back to Python
            return self._grep_python(base, pattern, include, single_file=False)

        # rg exit code 1 = no matches, 2 = error
        if proc.returncode == 2:
            err = stderr.decode("utf-8", errors="replace").strip()
            return ToolResult.fail(f"Invalid regex or rg error: {err}")

        raw = stdout.decode("utf-8", errors="replace")
        if not raw.strip():
            return ToolResult.ok(
                f"No matches for /{pattern}/ in {base}",
                match_count=0,
            )

        # Parse rg output: path:lineno:line
        matches: list[str] = []
        files_matched: set[str] = set()
        for line in raw.splitlines():
            if not line:
                continue
            # Make paths relative to working_dir
            try:
                m = _RG_LINE_RE.match(line)
                if m:
                    fpath, lineno, content = m.group(1), m.group(2), m.group(3)
                    # Make relative to working_dir
                    try:
                        rel = str(Path(fpath).relative_to(self.working_dir))
                    except ValueError:
                        rel = fpath
                    display = content.strip()
                    if len(display) > 200:
                        display = display[:200] + "…"
                    matches.append(f"{rel}:{lineno}| {display}")
                    files_matched.add(rel)
                else:
                    matches.append(line)
            except Exception:
                matches.append(line)

            if len(matches) >= overflow_cap:
                break

        return self._format_grep_result(matches, pattern, base, files_matched, max_matches, overflow_cap)

    def _grep_python(
        self,
        base: Path,
        pattern: str,
        include: str | None,
        single_file: bool,
    ) -> ToolResult:
        """Pure-Python fallback with a wall-clock budget to guard against ReDoS."""
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult.fail(f"Invalid regex: {e}")

        matches: list[str] = []
        files_matched: set[str] = set()
        max_matches = 500
        overflow_cap = max_matches * 4
        truncated = False

        deadline = time.monotonic() + _SEARCH_TIMEOUT_SECS
        files_since_check = 0
        _TIME_CHECK_INTERVAL = 50  # check clock every N files

        if single_file:
            candidates = iter([base])
        else:
            candidates = sorted(base.rglob("*"))

        for filepath in candidates:
            if not filepath.is_file():
                continue
            if any(part in SKIP_DIRS for part in filepath.parts):
                continue
            if not single_file and include and not fnmatch.fnmatch(filepath.name, include):
                continue
            if is_binary(filepath):
                continue

            # Wall-clock budget check (every N files)
            files_since_check += 1
            if files_since_check >= _TIME_CHECK_INTERVAL:
                files_since_check = 0
                if time.monotonic() > deadline:
                    return ToolResult.fail(
                        "grep search exceeded time budget; narrow the pattern "
                        "or add `include` to limit file types."
                    )

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
                    if len(matches) >= overflow_cap:
                        truncated = True
                        break
            if len(matches) >= overflow_cap:
                truncated = True
                break

        if len(matches) > max_matches:
            truncated = True

        if not matches:
            return ToolResult.ok(
                f"No matches for /{pattern}/ in {base}",
                match_count=0,
            )

        return self._format_grep_result(
            matches, pattern, base, files_matched, max_matches, overflow_cap
        )

    def _format_grep_result(
        self,
        matches: list[str],
        pattern: str,
        base: Path,
        files_matched: set[str],
        max_matches: int,
        overflow_cap: int,
    ) -> ToolResult:
        truncated = len(matches) > max_matches

        shown = matches[:max_matches]
        result = "\n".join(shown)
        meta: dict[str, Any] = {
            "match_count": len(shown),
            "file_count": len(files_matched),
        }

        if truncated:
            handle: str | None = None
            if self._truncation_store is not None:
                handle = self._truncation_store.store(
                    "\n".join(matches), tool_name="grep"
                )
            envelope = TruncationEnvelope(
                truncated_at=max_matches,
                unit="matches",
                total_hint=len(matches) if len(matches) < overflow_cap else None,
                peek_handle=handle,
                next_hint=(
                    "narrow with `include` or a tighter pattern; "
                    "scan stopped early — true total may be higher"
                    if len(matches) >= overflow_cap
                    else "narrow with `include` or a tighter pattern"
                ),
            )
            result += envelope.format_footer()
            meta.update(envelope.to_metadata())

        return ToolResult.ok(result, **meta)
