"""Edit tool — search-and-replace with fuzzy matching for resilience to LLM imprecision."""

from __future__ import annotations

import asyncio
import difflib
import os
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import resolve_path


# ── Fuzzy matching chain ──────────────────────────────────────────────────────
# LLMs are imprecise — they introduce smart quotes, whitespace changes,
# and Unicode artifacts. The matching chain tries increasingly lenient
# strategies until one finds a unique match.


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode artifacts that LLMs commonly introduce."""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",  # smart single quotes
        "\u201c": '"',
        "\u201d": '"',  # smart double quotes
        "\u2013": "-",
        "\u2014": "-",  # em/en dashes
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",  # non-breaking space
        "\u200b": "",  # zero-width space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return unicodedata.normalize("NFKC", text)


def _find_exact(content: str, search: str) -> list[int]:
    """Find all exact occurrences."""
    positions: list[int] = []
    start = 0
    while True:
        idx = content.find(search, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def _find_normalized(content: str, search: str) -> list[int]:
    """Find with Unicode normalization."""
    norm_content = _normalize_unicode(content)
    norm_search = _normalize_unicode(search)
    if norm_content == content and norm_search == search:
        return []  # No difference from exact
    return _find_exact(norm_content, norm_search)


def _find_whitespace_normalized(content: str, search: str) -> list[int]:
    """Find with whitespace normalization (collapse runs, strip trailing)."""

    def normalize_ws(text: str) -> str:
        lines = text.splitlines()
        return "\n".join(line.rstrip() for line in lines)

    norm_content = normalize_ws(content)
    norm_search = normalize_ws(search)
    if norm_content == content and norm_search == search:
        return []
    return _find_exact(norm_content, norm_search)


def _find_indentation_flexible(content: str, search: str) -> list[int]:
    """Find with flexible indentation (strip common leading whitespace)."""
    import textwrap

    dedented_search = textwrap.dedent(search)
    if dedented_search == search:
        return []

    # Try to find the dedented version in dedented content blocks
    content_lines = content.splitlines(keepends=True)
    search_lines = dedented_search.splitlines()
    if not search_lines:
        return []

    positions: list[int] = []
    for i in range(len(content_lines) - len(search_lines) + 1):
        block = content_lines[i : i + len(search_lines)]
        block_dedented = textwrap.dedent("".join(block)).splitlines()
        if block_dedented == search_lines:
            positions.append(sum(len(l) for l in content_lines[:i]))
    return positions


def find_match(content: str, search: str) -> tuple[int, str] | None:
    """Try matching strategies in order. Returns (position, strategy_name) or None.

    Only returns if exactly one match is found (unique).
    """
    strategies: list[tuple[str, Any]] = [
        ("exact", lambda: _find_exact(content, search)),
        ("unicode_normalized", lambda: _find_normalized(content, search)),
        ("whitespace_normalized", lambda: _find_whitespace_normalized(content, search)),
        ("indentation_flexible", lambda: _find_indentation_flexible(content, search)),
    ]

    for name, finder in strategies:
        positions = finder()
        if len(positions) == 1:
            return positions[0], name

    return None


# ── File mutation lock ────────────────────────────────────────────────────────
# Serialize edits to the same file, allow parallel edits to different files.

_file_locks: dict[str, asyncio.Lock] = {}


def _get_file_lock(path: str) -> asyncio.Lock:
    if path not in _file_locks:
        _file_locks[path] = asyncio.Lock()
    return _file_locks[path]


# ── EditTool ──────────────────────────────────────────────────────────────────


@dataclass
class EditTool:
    """Edit a file by search-and-replace with fuzzy matching.

    Supports multiple edits in one call. Each edit specifies an old_text
    to find and a new_text to replace it with. Edits are validated against
    the original file content, then applied in reverse position order so
    offsets stay stable.
    """

    name: str = "edit"
    description: str = (
        "Edit a file by replacing specific text. Provide old_text to find "
        "and new_text to replace it with. old_text must uniquely identify "
        "the target location. Supports multiple edits in one call."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Keep old_text as small as possible while still being unique in the file. "
        "Include a few lines of context around the change to ensure uniqueness. "
        "Merge nearby changes into one edit when possible. "
        "Always `read` the file first — never edit blind."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit.",
                    },
                    "edits": {
                        "type": "array",
                        "description": "List of edits to apply.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {
                                    "type": "string",
                                    "description": "Exact text to find (must be unique in the file).",
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "Text to replace old_text with.",
                                },
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                },
                "required": ["path", "edits"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = resolve_path(self.working_dir, arguments["path"])
        except ValueError as e:
            return ToolResult.fail(str(e))

        if not path.is_file():
            return ToolResult.fail(f"Not a file: {path}")

        edits = self._prepare_edits(arguments)
        if isinstance(edits, ToolResult):
            return edits

        async with _get_file_lock(str(path)):
            return await self._apply_edits(path, edits)

    def _prepare_edits(
        self, arguments: dict[str, Any]
    ) -> list[dict[str, str]] | ToolResult:
        """Normalize and validate edit arguments."""
        raw = arguments.get("edits")

        # Handle LLM quirk: edits sent as JSON string instead of array
        if isinstance(raw, str):
            import json

            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return ToolResult.fail("Could not parse `edits` — expected a JSON array.")

        if not isinstance(raw, list) or not raw:
            return ToolResult.fail("`edits` must be a non-empty array.")

        edits: list[dict[str, str]] = []
        for i, edit in enumerate(raw):
            if not isinstance(edit, dict):
                return ToolResult.fail(f"Edit {i} is not an object.")
            old = edit.get("old_text", "")
            new = edit.get("new_text", "")
            if not old:
                return ToolResult.fail(f"Edit {i}: `old_text` must not be empty.")
            edits.append({"old_text": old, "new_text": new})

        return edits

    async def _apply_edits(
        self, path: Path, edits: list[dict[str, str]]
    ) -> ToolResult:
        """Read file, find matches, apply edits, write atomically."""
        try:
            original = path.read_text(errors="replace")
        except (PermissionError, OSError) as e:
            return ToolResult.fail(f"Cannot read {path}: {e}")

        # Find all match positions
        matches: list[tuple[int, str, str, str]] = []  # (pos, old, new, strategy)
        for edit in edits:
            old_text = edit["old_text"]
            new_text = edit["new_text"]

            result = find_match(original, old_text)
            if result is None:
                # Check if there are multiple matches
                exact = _find_exact(original, old_text)
                if len(exact) > 1:
                    return ToolResult.fail(
                        f"old_text matched {len(exact)} locations — "
                        f"it must be unique. Add more context to disambiguate.\n\n"
                        f"old_text preview: {old_text[:100]!r}"
                    )
                # Try showing nearby content
                close = difflib.get_close_matches(
                    old_text[:80],
                    original.splitlines(),
                    n=3,
                    cutoff=0.4,
                )
                hint = ""
                if close:
                    hint = "\nSimilar lines in file:\n" + "\n".join(
                        f"  {l}" for l in close
                    )
                return ToolResult.fail(
                    f"old_text not found in {path.name}.{hint}\n\n"
                    f"old_text preview: {old_text[:100]!r}"
                )

            pos, strategy = result
            matches.append((pos, old_text, new_text, strategy))

        # Check for overlapping edits
        sorted_matches = sorted(matches, key=lambda m: m[0])
        for i in range(len(sorted_matches) - 1):
            end_i = sorted_matches[i][0] + len(sorted_matches[i][1])
            start_next = sorted_matches[i + 1][0]
            if end_i > start_next:
                return ToolResult.fail(
                    "Edits overlap — merge them into a single edit."
                )

        # Apply in reverse order so positions stay stable
        content = original
        for pos, old_text, new_text, strategy in reversed(sorted_matches):
            content = content[:pos] + new_text + content[pos + len(old_text) :]

        # Atomic write
        try:
            fd, tmp = tempfile.mkstemp(
                dir=path.parent, suffix=".tmp", prefix=".taui_edit_"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                Path(tmp).replace(path)
            except Exception:
                Path(tmp).unlink(missing_ok=True)
                raise
        except (PermissionError, OSError) as e:
            return ToolResult.fail(f"Cannot write {path}: {e}")

        # Generate diff for the response
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            n=3,
        )
        diff_text = "".join(diff)

        strategies_used = list({m[3] for m in matches})
        return ToolResult.ok(
            diff_text if diff_text else "(no changes)",
            path=str(path),
            edits_applied=len(matches),
            strategies=strategies_used,
        )
