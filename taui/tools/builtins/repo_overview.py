"""Repo overview tool — one-shot project survey."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import SKIP_DIRS


@dataclass
class RepoOverviewTool:
    """Generate a one-shot overview of the current project."""

    name: str = "repo_overview"
    description: str = (
        "Generate a concise overview of the current project: languages, "
        "structure, entry points, recent commits, and key files. "
        "Useful as a first step when exploring an unfamiliar codebase."
    )
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "max_depth": {
                        "type": "integer",
                        "description": (
                            "Max directory depth for tree listing. Default 2."
                        ),
                    },
                },
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        max_depth = arguments.get("max_depth", 2)
        parts: list[str] = []

        wd = self.working_dir
        parts.append(f"# Project: {wd.name}")
        parts.append(f"Root: {wd}")
        parts.append("")

        # Language breakdown by file extension
        ext_counts: dict[str, int] = {}
        try:
            for p in wd.rglob("*"):
                if p.is_file() and not _should_skip(p, wd):
                    ext = p.suffix.lower() or "(no ext)"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
        except Exception:
            pass

        if ext_counts:
            parts.append("## Languages (by file extension)")
            for ext, count in sorted(
                ext_counts.items(), key=lambda x: -x[1]
            )[:15]:
                lang = _EXT_TO_LANG.get(ext, ext)
                parts.append(f"  {lang}: {count} files")
            parts.append("")

        # Directory structure (limited depth)
        parts.append(f"## Directory structure (depth {max_depth})")
        tree_lines = _tree(wd, max_depth=max_depth)
        parts.extend(tree_lines[:80])
        if len(tree_lines) > 80:
            parts.append(f"  ... ({len(tree_lines) - 80} more entries)")
        parts.append("")

        # Entry points
        entry_files = _find_entry_points(wd)
        if entry_files:
            parts.append("## Likely entry points")
            for ef in entry_files[:10]:
                parts.append(f"  {ef}")
            parts.append("")

        # Git info
        git_info = _git_summary(wd)
        if git_info:
            parts.append("## Git")
            parts.append(git_info)
            parts.append("")

        # Key config files
        config_files = _find_config_files(wd)
        if config_files:
            parts.append("## Config files")
            for cf in config_files:
                parts.append(f"  {cf}")
            parts.append("")

        return ToolResult.ok("\n".join(parts))


# Re-use the shared skip set from common.py (single source of truth).
_SKIP_DIRS = SKIP_DIRS

_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript/JSX", ".jsx": "JavaScript/JSX",
    ".rs": "Rust", ".go": "Go", ".java": "Java",
    ".c": "C", ".h": "C/C++ Header", ".cpp": "C++", ".cc": "C++",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".kt": "Kotlin", ".scala": "Scala", ".cs": "C#",
    ".md": "Markdown", ".json": "JSON", ".yaml": "YAML",
    ".yml": "YAML", ".toml": "TOML", ".xml": "XML",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".sql": "SQL", ".r": "R", ".jl": "Julia",
}


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _tree(root: Path, max_depth: int = 2) -> list[str]:
    lines: list[str] = []
    _tree_recurse(root, "", 0, max_depth, lines)
    return lines


def _tree_recurse(
    path: Path, prefix: str, depth: int, max_depth: int,
    lines: list[str],
) -> None:
    if depth > max_depth:
        return
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return
    dirs = [e for e in entries if e.is_dir() and e.name not in _SKIP_DIRS]
    files = [e for e in entries if e.is_file() and not e.name.startswith(".")]
    items = dirs + files[:20]
    for i, entry in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{prefix}{connector}{entry.name}{suffix}")
        if entry.is_dir() and depth < max_depth:
            ext = "    " if is_last else "│   "
            _tree_recurse(entry, prefix + ext, depth + 1, max_depth, lines)


def _find_entry_points(root: Path) -> list[str]:
    patterns = [
        "main.py", "app.py", "manage.py", "setup.py", "pyproject.toml",
        "package.json", "Cargo.toml", "go.mod", "Makefile", "CMakeLists.txt",
        "index.ts", "index.js", "src/main.rs", "cmd/main.go",
    ]
    found = []
    for pat in patterns:
        p = root / pat
        if p.exists():
            found.append(pat)
    return found


def _git_summary(root: Path) -> str:
    parts = []
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=root, timeout=5,
        )
        if branch.returncode == 0:
            parts.append(f"Branch: {branch.stdout.strip()}")
    except Exception:
        return ""

    try:
        log = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, cwd=root, timeout=5,
        )
        if log.returncode == 0 and log.stdout.strip():
            parts.append("Recent commits:")
            for line in log.stdout.strip().splitlines()[:5]:
                parts.append(f"  {line}")
    except Exception:
        pass

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=root, timeout=5,
        )
        if status.returncode == 0:
            lines = status.stdout.strip().splitlines()
            if lines:
                parts.append(f"Working tree: {len(lines)} changed files")
            else:
                parts.append("Working tree: clean")
    except Exception:
        pass

    return "\n".join(parts)


def _find_config_files(root: Path) -> list[str]:
    names = [
        "pyproject.toml", "setup.cfg", "setup.py", "requirements.txt",
        "package.json", "tsconfig.json", "Cargo.toml", "go.mod",
        "Makefile", "Dockerfile", "docker-compose.yml",
        ".github/workflows", ".gitignore", "README.md",
    ]
    found = []
    for n in names:
        p = root / n
        if p.exists():
            found.append(n)
    return found
