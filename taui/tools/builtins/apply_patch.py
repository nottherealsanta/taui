"""Apply patch tool — multi-hunk unified diff edits in one call."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import resolve_path


@dataclass
class ApplyPatchTool:
    """Apply a unified diff patch to one or more files."""

    name: str = "apply_patch"
    description: str = (
        "Apply a unified diff patch to modify files. Supports multi-hunk "
        "and multi-file patches. More efficient than multiple edit calls "
        "for large refactors."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    requires_approval: bool = True
    schema: dict[str, Any] = field(default=None)
    working_dir: Path | None = field(default=None, repr=False)
    _path_guard: Any = field(default=None, repr=False)
    _file_tracker: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": (
                            "Unified diff patch text. Use standard format:\n"
                            "--- a/path/to/file\n"
                            "+++ b/path/to/file\n"
                            "@@ -start,count +start,count @@\n"
                            " context line\n"
                            "-removed line\n"
                            "+added line"
                        ),
                    },
                },
                "required": ["patch"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        patch_text = arguments.get("patch", "")
        if not patch_text.strip():
            return ToolResult.fail("Patch text is required.")

        try:
            hunks = _parse_patch(patch_text)
        except ValueError as e:
            return ToolResult.fail(f"Invalid patch format: {e}")

        if not hunks:
            return ToolResult.fail("No hunks found in patch.")

        base = self.working_dir or Path(".")
        results = []

        for file_path, file_hunks in hunks.items():
            # Keep patched files inside the workspace; a patch header like
            # `--- a/../../etc/x` would otherwise write outside it.
            try:
                path = resolve_path(base, file_path)
            except ValueError as exc:
                return ToolResult.fail(str(exc))

            if self._path_guard:
                guard_result = self._path_guard(path)
                if guard_result is not None:
                    return guard_result

            if self._file_tracker:
                error = self._file_tracker.check_before_write(path)
                if error:
                    return ToolResult.fail(error)

            if not path.exists():
                content = _apply_hunks_to_new(file_hunks)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                results.append(f"Created {file_path}")
            else:
                original = path.read_text()
                lines = original.splitlines(keepends=True)
                try:
                    new_lines = _apply_hunks(lines, file_hunks)
                except ValueError as e:
                    return ToolResult.fail(f"Failed to apply patch to {file_path}: {e}")
                path.write_text("".join(new_lines))
                results.append(f"Patched {file_path}")

            if self._file_tracker:
                self._file_tracker.update_after_write(path)

        return ToolResult.ok("\n".join(results))


def _parse_patch(text: str) -> dict[str, list[dict]]:
    """Parse a unified diff into {filepath: [hunks]}."""
    files: dict[str, list[dict]] = {}
    current_file: str | None = None
    current_hunk: dict | None = None

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n\r")

        if stripped.startswith("--- a/") or (
            stripped.startswith("--- ") and not stripped.startswith("--- /dev/null")
        ):
            continue

        if stripped.startswith("/dev/null") or stripped == "--- /dev/null":
            continue

        if stripped.startswith("+++ b/") or stripped.startswith("+++ "):
            path = stripped.split("+++ ", 1)[1]
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            if current_file not in files:
                files[current_file] = []
            continue

        hunk_match = re.match(
            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
            stripped,
        )
        if hunk_match:
            if current_file is None:
                raise ValueError("Hunk without file header")
            current_hunk = {
                "old_start": int(hunk_match.group(1)),
                "old_count": int(hunk_match.group(2) or 1),
                "new_start": int(hunk_match.group(3)),
                "new_count": int(hunk_match.group(4) or 1),
                "lines": [],
            }
            files[current_file].append(current_hunk)
            continue

        if current_hunk is not None:
            if stripped.startswith("+") or stripped.startswith("-") or stripped.startswith(" "):
                current_hunk["lines"].append(line.rstrip("\n\r"))
            elif stripped == "":
                current_hunk["lines"].append(" ")

    return files


def _apply_hunks(lines: list[str], hunks: list[dict]) -> list[str]:
    """Apply hunks to a list of lines. Returns new lines."""
    clean = [ln.rstrip("\n\r") for ln in lines]
    offset = 0

    for hunk in hunks:
        start = hunk["old_start"] - 1 + offset
        old_lines: list[str] = []
        new_lines: list[str] = []

        for line in hunk["lines"]:
            if line.startswith("-"):
                old_lines.append(line[1:])
            elif line.startswith("+"):
                new_lines.append(line[1:])
            elif line.startswith(" "):
                old_lines.append(line[1:])
                new_lines.append(line[1:])

        end = start + len(old_lines)
        if end > len(clean):
            raise ValueError(f"Hunk at line {hunk['old_start']} extends beyond file end")

        actual = clean[start:end]
        if actual != old_lines:
            actual_stripped = [ln.rstrip() for ln in actual]
            old_stripped = [ln.rstrip() for ln in old_lines]
            if actual_stripped != old_stripped:
                raise ValueError(
                    f"Context mismatch at line {hunk['old_start']}: "
                    f"expected {old_lines[:3]}... got {actual[:3]}..."
                )

        clean[start:end] = new_lines
        offset += len(new_lines) - len(old_lines)

    return [ln + "\n" for ln in clean]


def _apply_hunks_to_new(hunks: list[dict]) -> str:
    """Create a new file from patch hunks (all additions)."""
    lines = []
    for hunk in hunks:
        for line in hunk["lines"]:
            if line.startswith("+"):
                lines.append(line[1:])
            elif line.startswith(" "):
                lines.append(line[1:])
    return "\n".join(lines) + "\n" if lines else ""
