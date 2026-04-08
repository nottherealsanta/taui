"""Fuzzy matching chain for the edit tool.

Tries a sequence of increasingly relaxed matching strategies to find
``old_string`` within ``content``.

1. Exact match
2. Line-trimmed (ignore leading/trailing whitespace per line)
3. Whitespace-normalized (collapse runs of whitespace)
4. Indentation-flexible (strip common indent prefix)
5. Block anchor (match first+last line, score middle lines by similarity)
"""

from __future__ import annotations

from typing import Generator


# ---------------------------------------------------------------------------
# Individual replacers – each yields the actual substring(s) found in *content*
# that correspond to the search *find* string.
# ---------------------------------------------------------------------------


def _exact_match(content: str, find: str) -> Generator[str, None, None]:
    if find in content:
        yield find


def _line_trimmed(content: str, find: str) -> Generator[str, None, None]:
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    if not search_lines:
        return
    for i in range(len(original_lines) - len(search_lines) + 1):
        if all(
            original_lines[i + j].strip() == search_lines[j].strip()
            for j in range(len(search_lines))
        ):
            block = "\n".join(original_lines[i : i + len(search_lines)])
            yield block


def _whitespace_normalized(content: str, find: str) -> Generator[str, None, None]:
    import re

    def _norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    norm_find = _norm(find)
    lines = content.split("\n")
    find_lines = find.split("\n")

    # Single line
    for line in lines:
        if _norm(line) == norm_find:
            yield line

    # Multi-line
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = "\n".join(lines[i : i + len(find_lines)])
            if _norm(block) == norm_find:
                yield block


def _indentation_flexible(content: str, find: str) -> Generator[str, None, None]:
    def _remove_indent(text: str) -> str:
        text_lines = text.split("\n")
        non_empty = [l for l in text_lines if l.strip()]
        if not non_empty:
            return text
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        return "\n".join(
            l[min_indent:] if l.strip() else l for l in text_lines
        )

    norm_find = _remove_indent(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i : i + len(find_lines)])
        if _remove_indent(block) == norm_find:
            yield block


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    rows = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        prev = rows[:]
        rows[0] = i + 1
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            rows[j + 1] = min(prev[j + 1] + 1, rows[j] + 1, prev[j] + cost)
    return rows[-1]


def _block_anchor(content: str, find: str) -> Generator[str, None, None]:
    """Match by first+last line anchors with similarity scoring of middle."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if len(search_lines) < 3:
        return
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    if len(search_lines) < 3:
        return

    first_search = search_lines[0].strip()
    last_search = search_lines[-1].strip()

    candidates: list[tuple[int, int]] = []
    for i, line in enumerate(original_lines):
        if line.strip() != first_search:
            continue
        for j in range(i + 2, len(original_lines)):
            if original_lines[j].strip() == last_search:
                candidates.append((i, j))
                break

    if not candidates:
        return

    best_match: tuple[int, int] | None = None
    best_similarity = -1.0

    for start_line, end_line in candidates:
        actual_size = end_line - start_line + 1
        lines_to_check = min(len(search_lines) - 2, actual_size - 2)
        if lines_to_check <= 0:
            similarity = 1.0
        else:
            similarity = 0.0
            for k in range(1, lines_to_check + 1):
                orig = original_lines[start_line + k].strip()
                search = search_lines[k].strip()
                max_len = max(len(orig), len(search))
                if max_len == 0:
                    continue
                dist = _levenshtein(orig, search)
                similarity += (1 - dist / max_len) / lines_to_check

        if similarity > best_similarity:
            best_similarity = similarity
            best_match = (start_line, end_line)

    threshold = 0.3 if len(candidates) > 1 else 0.0
    if best_match is not None and best_similarity >= threshold:
        block = "\n".join(original_lines[best_match[0] : best_match[1] + 1])
        yield block


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_REPLACERS = [
    _exact_match,
    _line_trimmed,
    _whitespace_normalized,
    _indentation_flexible,
    _block_anchor,
]


def find_match(content: str, old_string: str) -> tuple[str, int] | None:
    """Try each replacer in order. Return ``(matched_text, count)`` or None.

    *matched_text* is the actual substring found in *content* (may differ from
    *old_string* in whitespace).  *count* is how many times it appears.
    """
    for replacer in _REPLACERS:
        for matched in replacer(content, old_string):
            idx = content.find(matched)
            if idx == -1:
                continue
            count = content.count(matched)
            return matched, count
    return None
