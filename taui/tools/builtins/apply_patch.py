"""ApplyPatch tool — apply unified diffs to files.

Preferred by GPT/OpenAI models over edit (old_string/new_string).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class ApplyPatchTool:
    """Apply a unified diff patch to one or more files."""

    name: str = "apply_patch"
    description: str = (
        "Apply a unified diff (patch) to modify files. Provide the patch in "
        "standard unified diff format. Each file in the patch must have been "
        "read first. Preferred for complex multi-line edits."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.FILE_WRITE

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "The unified diff to apply",
                    },
                },
                "required": ["patch"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        patch_text = arguments.get("patch")
        if not isinstance(patch_text, str) or not patch_text.strip():
            return normalize_tool_error(
                "Invalid apply_patch arguments: 'patch' must be a non-empty string."
            )

        try:
            file_patches = _parse_unified_diff(patch_text)
        except ValueError as exc:
            return normalize_tool_error(f"Failed to parse patch: {exc}")

        if not file_patches:
            return normalize_tool_error("No file patches found in the diff.")

        results: list[str] = []
        for fp in file_patches:
            file_path_str = fp["path"]
            hunks = fp["hunks"]

            try:
                path = resolve_path(context, file_path_str)
            except ValueError as exc:
                results.append(f"SKIP {file_path_str}: {exc}")
                continue

            if context.session.read_status(path) != "success":
                # For new files, allow creating
                if not path.exists():
                    new_content = _build_new_file(hunks)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(new_content, encoding="utf-8")
                    results.append(f"CREATED {path}")
                    continue
                results.append(f"SKIP {file_path_str}: must read file before patching")
                continue

            if not path.exists():
                results.append(f"SKIP {file_path_str}: file not found")
                continue

            try:
                original = path.read_text(encoding="utf-8")
            except OSError as exc:
                results.append(f"SKIP {file_path_str}: {exc}")
                continue

            try:
                updated = _apply_hunks(original, hunks)
            except ValueError as exc:
                results.append(f"FAIL {file_path_str}: {exc}")
                continue

            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=path.parent, delete=False
                ) as tmp:
                    tmp.write(updated)
                    tmp_path = Path(tmp.name)
                tmp_path.replace(path)
                results.append(f"OK {path}")
            except OSError as exc:
                results.append(f"FAIL {file_path_str}: could not write: {exc}")

        return ToolResult.ok(
            "\n".join(results),
            metadata={"files": len(file_patches), "results": results},
        )


def _parse_unified_diff(patch: str) -> list[dict[str, Any]]:
    """Parse a unified diff into a list of file patches."""
    file_patches: list[dict[str, Any]] = []
    lines = patch.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Look for --- a/path or --- path
        if line.startswith("--- "):
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                continue
            plus_line = lines[i]
            path = _extract_path(plus_line[4:])
            i += 1

            hunks: list[dict[str, Any]] = []
            while i < len(lines):
                if lines[i].startswith("@@ "):
                    hunk = _parse_hunk_header(lines[i])
                    i += 1
                    hunk_lines: list[str] = []
                    while i < len(lines):
                        if (
                            lines[i].startswith("@@ ")
                            or lines[i].startswith("--- ")
                            or lines[i].startswith("diff ")
                        ):
                            break
                        hunk_lines.append(lines[i])
                        i += 1
                    hunk["lines"] = hunk_lines
                    hunks.append(hunk)
                elif lines[i].startswith("--- ") or lines[i].startswith("diff "):
                    break
                else:
                    i += 1

            file_patches.append({"path": path, "hunks": hunks})
        else:
            i += 1

    return file_patches


def _extract_path(raw: str) -> str:
    """Extract file path from diff header, stripping a/ b/ prefix and timestamps."""
    path = raw.strip()
    # Remove tab-separated timestamp
    if "\t" in path:
        path = path.split("\t")[0]
    # Strip a/ or b/ prefix
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunk_header(line: str) -> dict[str, Any]:
    m = _HUNK_RE.match(line)
    if not m:
        raise ValueError(f"Invalid hunk header: {line}")
    return {
        "old_start": int(m.group(1)),
        "old_count": int(m.group(2)) if m.group(2) else 1,
        "new_start": int(m.group(3)),
        "new_count": int(m.group(4)) if m.group(4) else 1,
    }


def _apply_hunks(original: str, hunks: list[dict[str, Any]]) -> str:
    """Apply hunks to the original content."""
    original_lines = original.split("\n")
    # Process hunks in reverse order to preserve line numbers
    sorted_hunks = sorted(hunks, key=lambda h: h["old_start"], reverse=True)

    for hunk in sorted_hunks:
        old_start = hunk["old_start"] - 1  # Convert to 0-indexed
        hunk_lines = hunk["lines"]

        # Extract old and new lines from the hunk
        old_lines: list[str] = []
        new_lines: list[str] = []
        for hl in hunk_lines:
            if hl.startswith("-"):
                old_lines.append(hl[1:])
            elif hl.startswith("+"):
                new_lines.append(hl[1:])
            elif hl.startswith(" "):
                old_lines.append(hl[1:])
                new_lines.append(hl[1:])
            elif hl == "\\ No newline at end of file":
                continue
            else:
                # Context line without prefix
                old_lines.append(hl)
                new_lines.append(hl)

        # Verify old lines match (with some tolerance for trailing whitespace)
        old_count = hunk.get("old_count", len(old_lines))
        section = original_lines[old_start : old_start + old_count]
        matched = len(section) == len(old_lines)
        if matched:
            for a, b in zip(section, old_lines):
                if a.rstrip() != b.rstrip():
                    matched = False
                    break

        if not matched:
            # Try fuzzy match: slide the hunk up/down by a few lines
            found = False
            for offset in range(-3, 4):
                idx = old_start + offset
                if idx < 0:
                    continue
                section = original_lines[idx : idx + old_count]
                if len(section) != len(old_lines):
                    continue
                if all(a.rstrip() == b.rstrip() for a, b in zip(section, old_lines)):
                    old_start = idx
                    found = True
                    break
            if not found:
                raise ValueError(
                    f"Hunk at line {hunk['old_start']} does not match file content."
                )

        original_lines[old_start : old_start + old_count] = new_lines

    return "\n".join(original_lines)


def _build_new_file(hunks: list[dict[str, Any]]) -> str:
    """Build file content from hunks (for creating new files)."""
    lines: list[str] = []
    for hunk in hunks:
        for hl in hunk["lines"]:
            if hl.startswith("+"):
                lines.append(hl[1:])
            elif hl.startswith(" "):
                lines.append(hl[1:])
    return "\n".join(lines)
