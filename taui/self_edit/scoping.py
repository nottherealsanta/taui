"""Path allowlist for self-edit tool scoping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taui.tools.base import Tool, ToolCategory, ToolResult


def self_edit_roots(project_working_dir: Path) -> tuple[Path, Path]:
    """Return the only filesystem roots self-edit tools may touch."""
    return (Path.home() / ".taui", project_working_dir / ".taui")


def self_edit_working_dir(project_working_dir: Path, scope: str) -> Path:
    """Return the active cwd for self-edit tools."""
    if scope == "project":
        return project_working_dir / ".taui"
    return Path.home() / ".taui"


class PathAllowlist:
    """Checks whether a path falls under one of the allowlisted roots."""

    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        roots = roots or self_edit_roots(Path.cwd())
        resolved: list[Path] = []
        for root in roots:
            try:
                resolved.append(root.resolve())
            except OSError:
                resolved.append(root.absolute())
        self._roots = tuple(resolved)

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    def allows(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        return any(
            resolved == root or _is_relative_to(resolved, root)
            for root in self._roots
        )


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


@dataclass
class _ScopedTool:
    """Wraps an inner Tool with a path-allowlist guard.

    Created instead of mutating the inner tool so the main session's
    registry keeps unscoped behavior.
    """

    name: str
    description: str
    schema: dict[str, Any]
    category: ToolCategory
    _inner: Tool
    _allowlist: PathAllowlist
    _relative_root: Path

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        normalized_arguments = dict(arguments)
        candidate_paths = _extract_paths(arguments)
        for key, path_str in candidate_paths:
            candidate = Path(str(path_str)).expanduser()
            if not candidate.is_absolute():
                candidate = self._relative_root / candidate
            if not self._allowlist.allows(candidate):
                roots = "\n".join(f"  {r}" for r in self._allowlist.roots)
                return ToolResult.fail(
                    f"Self-edit agent: path not in allowed config directories: {path_str}\n"
                    f"Allowed roots:\n{roots}"
                )
            normalized_arguments[key] = str(candidate.resolve())
        return await self._inner.execute(normalized_arguments)


def _extract_paths(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """Pull path-like fields from a tool call's arguments."""
    paths: list[tuple[str, str]] = []
    for key in ("path", "file_path", "filePath", "old_path", "new_path"):
        value = arguments.get(key)
        if value:
            paths.append((key, str(value)))
    return paths


def wrap_tool_with_allowlist(
    tool: Tool,
    allowlist: PathAllowlist,
    *,
    relative_root: Path | None = None,
) -> Tool:
    """Return a NEW tool wrapping the inner one with a path-allowlist guard."""
    return _ScopedTool(
        name=tool.name,
        description=tool.description,
        schema=tool.schema,
        category=tool.category,
        _inner=tool,
        _allowlist=allowlist,
        _relative_root=relative_root or Path.cwd(),
    )
