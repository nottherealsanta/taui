"""Edit tool — search-and-replace with fuzzy matching for resilience to LLM imprecision."""

from __future__ import annotations

import asyncio
import difflib
import os
import tempfile
import textwrap
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import resolve_path
from taui.tools.file_tracker import FileTracker

# ── Fuzzy matching chain ──────────────────────────────────────────────────────
# LLMs are imprecise — they introduce smart quotes, whitespace changes,
# and Unicode artifacts. The matching chain tries increasingly lenient
# strategies until one finds a unique match.
#
# INVARIANT: every strategy returns a *span* (start, end) into the ORIGINAL
# content so that ``content[start:end]`` is the exact text to be replaced.
# This avoids the corruption bug where normalised positions were used
# against the un-normalised content.

# Return type for all finders: list of (start, end) spans into original content.
Span = tuple[int, int]


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


def _find_exact(content: str, search: str) -> list[Span]:
    """Find all exact occurrences — spans into original content."""
    spans: list[Span] = []
    start = 0
    while True:
        idx = content.find(search, start)
        if idx == -1:
            break
        spans.append((idx, idx + len(search)))
        start = idx + 1
    return spans


def _find_normalized(content: str, search: str) -> list[Span]:
    """Find with Unicode normalization — returns spans into *original* content.

    Uses a line-block scan: normalize each candidate block of lines from the
    original and compare to the normalized search.  The returned span covers
    the original lines that matched.
    """
    norm_search = _normalize_unicode(search)
    # Quick bail: if normalizing changes nothing on both sides, exact already covered it.
    if _normalize_unicode(content) == content and norm_search == search:
        return []

    return _line_block_scan(content, search, _normalize_unicode)


def _find_whitespace_normalized(content: str, search: str) -> list[Span]:
    """Find with whitespace normalization (strip trailing whitespace per line).

    Returns spans into *original* content via a line-block scan.
    """

    def normalize_ws(text: str) -> str:
        lines = text.splitlines()
        return "\n".join(line.rstrip() for line in lines)

    # Quick bail: no difference from exact.
    if normalize_ws(content) == content and normalize_ws(search) == search:
        return []

    return _line_block_scan(content, search, normalize_ws)


def _find_indentation_flexible(content: str, search: str) -> list[Span]:
    """Find with flexible indentation (strip common leading whitespace).

    Returns spans into *original* content via a line-block scan.
    """
    dedented_search = textwrap.dedent(search)
    if dedented_search == search:
        return []

    def normalize_indent(text: str) -> str:
        return textwrap.dedent(text)

    return _line_block_scan(content, search, normalize_indent)


# ── Line-block scanner (shared by all fuzzy strategies) ───────────────────────


def _line_block_scan(
    content: str,
    search: str,
    normalize: Any,
) -> list[Span]:
    """Scan *content* for blocks of lines that, when normalized, match the
    normalized *search*.

    Returns a list of ``(start, end)`` spans into the **original** content.
    This is the key correctness invariant: positions always refer to the
    un-normalised text so that ``content[start:end]`` is safe to splice.
    """
    content_lines = content.splitlines(keepends=True)
    search_norm = normalize(search)
    search_norm_lines = search_norm.splitlines()

    if not search_norm_lines:
        return []

    n_search = len(search_norm_lines)
    spans: list[Span] = []

    # Pre-compute cumulative offsets for each content line
    offsets: list[int] = []
    offset = 0
    for line in content_lines:
        offsets.append(offset)
        offset += len(line)
    # Sentinel: total length of content
    offsets.append(offset)

    for i in range(len(content_lines) - n_search + 1):
        block_text = "".join(content_lines[i : i + n_search])
        block_norm = normalize(block_text)
        block_norm_lines = block_norm.splitlines()
        if block_norm_lines == search_norm_lines:
            span_start = offsets[i]
            span_end = offsets[i + n_search]

            # If the search text doesn't end with a line terminator but the
            # matched block does (because splitlines strips them), trim the
            # trailing line terminator from the span so the splice preserves it.
            if search and search[-1] not in '\n\r':
                if span_end > span_start and content[span_end - 1] == '\n':
                    span_end -= 1
                if span_end > span_start and content[span_end - 1] == '\r':
                    span_end -= 1

            spans.append((span_start, span_end))

    return spans


def find_match(content: str, search: str) -> tuple[Span, str] | None:
    """Try matching strategies in order. Returns ((start, end), strategy_name) or None.

    Only returns if exactly one match is found (unique).
    """
    strategies: list[tuple[str, Any]] = [
        ("exact", lambda: _find_exact(content, search)),
        ("unicode_normalized", lambda: _find_normalized(content, search)),
        ("whitespace_normalized", lambda: _find_whitespace_normalized(content, search)),
        ("indentation_flexible", lambda: _find_indentation_flexible(content, search)),
    ]

    for name, finder in strategies:
        spans = finder()
        if len(spans) == 1:
            return spans[0], name

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
    requires_approval: bool = True
    working_dir: Path = field(default_factory=Path.cwd)
    _path_guard: Any = None
    _file_tracker: FileTracker | None = None
    guidelines: str = (
        "Keep old_text as small as possible while still being unique in the file. "
        "Include a few lines of context around the change to ensure uniqueness. "
        "Merge nearby changes into one edit when possible. "
        "Always `read` the file first — never edit blind."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]
    output_schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

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
                                    "description": (
                                        "Exact text to find (must be unique in the file)."
                                    ),
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
        if self.output_schema is None:
            self.output_schema = {
                "type": "object",
                "properties": {
                    "diff": {"type": "string", "description": "Unified diff of changes"},
                    "lines_changed": {"type": "integer"},
                },
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

        # Find all match spans  —  each entry is (start, end, old_text, new_text, strategy)
        matches: list[tuple[int, int, str, str, str]] = []
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
                        f"  {line}" for line in close
                    )
                return ToolResult.fail(
                    f"old_text not found in {path.name}.{hint}\n\n"
                    f"old_text preview: {old_text[:100]!r}"
                )

            span, strategy = result
            start, end = span

            # Safety net: verify that the matched span, under the strategy's
            # normalization, actually equals the normalised search text.
            # Compare via splitlines() to stay consistent with the line-block
            # scanner (which ignores trailing-newline differences).
            matched_text = original[start:end]
            if strategy == "exact":
                # Exact must literally match
                if matched_text != old_text:
                    return ToolResult.fail(
                        f"Internal match verification failed for edit "
                        f"(strategy={strategy}). Please provide exact text."
                    )
            else:
                # Fuzzy: compare under the matching normalisation (line-wise)
                normalizers = {
                    "unicode_normalized": _normalize_unicode,
                    "whitespace_normalized": lambda t: "\n".join(
                        line.rstrip() for line in t.splitlines()
                    ),
                    "indentation_flexible": textwrap.dedent,
                }
                norm_fn = normalizers.get(strategy)
                if norm_fn and (
                    norm_fn(matched_text).splitlines()
                    != norm_fn(old_text).splitlines()
                ):
                    return ToolResult.fail(
                        f"Internal match verification failed for edit "
                        f"(strategy={strategy}). Please provide exact text."
                    )

            matches.append((start, end, old_text, new_text, strategy))

        # Check for overlapping edits — using spans
        sorted_matches = sorted(matches, key=lambda m: m[0])
        for i in range(len(sorted_matches) - 1):
            end_i = sorted_matches[i][1]  # end of span i
            start_next = sorted_matches[i + 1][0]  # start of span i+1
            if end_i > start_next:
                return ToolResult.fail(
                    "Edits overlap — merge them into a single edit."
                )

        # Apply in reverse order so positions stay stable
        content = original
        for start, end, old_text, new_text, strategy in reversed(sorted_matches):
            content = content[:start] + new_text + content[end:]

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

        strategies_used = list({m[4] for m in matches})
        if self._file_tracker is not None:
            self._file_tracker.update_after_write(path)
        return ToolResult.ok(
            diff_text if diff_text else "(no changes)",
            path=str(path),
            edits_applied=len(matches),
            strategies=strategies_used,
        )
