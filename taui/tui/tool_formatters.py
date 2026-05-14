"""Per-tool output formatters for TUI display.

Transforms raw tool output into richer display formats.
"""

from __future__ import annotations

import re


def format_tool_output(
    tool_name: str, content: str, *, verbose: bool = False
) -> str:
    """Format tool output for TUI display.

    Returns a compact summary for known tools, or the raw content
    if verbose or unrecognized.
    """
    if verbose:
        return content

    formatter = _FORMATTERS.get(tool_name)
    if formatter:
        try:
            return formatter(content)
        except Exception:
            return content
    return content


def _format_edit(content: str) -> str:
    """Compact edit result: show file + line count."""
    # Extract key info from edit result
    if "successfully" in content.lower() or "applied" in content.lower():
        lines = content.strip().split("\n")
        return lines[0][:100] if lines else content
    return content


def _format_read(content: str) -> str:
    """Compact read result: show line count."""
    lines = content.split("\n")
    if len(lines) > 5:
        return f"({len(lines)} lines)"
    return content


def _format_grep(content: str) -> str:
    """Compact grep result: show match count."""
    lines = [ln for ln in content.strip().split("\n") if ln.strip()]
    if len(lines) > 3:
        return f"{len(lines)} matches found"
    return content


def _format_bash(content: str) -> str:
    """Compact bash result: truncate long output."""
    lines = content.split("\n")
    if len(lines) > 10:
        head = "\n".join(lines[:5])
        return f"{head}\n... ({len(lines) - 5} more lines)"
    return content


def _format_diff(content: str) -> str:
    """Extract diff stats from apply_patch output."""
    added = len(re.findall(r"^\+[^+]", content, re.MULTILINE))
    removed = len(re.findall(r"^-[^-]", content, re.MULTILINE))
    if added or removed:
        return f"+{added}/-{removed} lines changed"
    return content


_FORMATTERS: dict[str, callable] = {
    "edit": _format_edit,
    "read": _format_read,
    "grep": _format_grep,
    "bash": _format_bash,
    "apply_patch": _format_diff,
    "write": _format_edit,
}
