"""Per-tool argument and output formatters for ToolStatusWidget.

Each formatter returns plain text (no Rich markup) for the *header* line
showing the tool's arguments, and the *body* lines showing a structured
summary of its output. The widget wraps these in its own color styling.
"""

from __future__ import annotations

import re
from typing import Any


_MAX_INLINE_LEN = 150


def _trunc(s: str, n: int) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Argument formatters ──────────────────────────────────────────────────────


def _fmt_args_generic(arguments: dict[str, Any]) -> str:
    parts = []
    for k, v in arguments.items():
        sv = str(v)
        parts.append(f"{k}={_trunc(sv, 40)}")
    return ", ".join(parts)


def _fmt_args_read(arguments: dict[str, Any]) -> str:
    path = arguments.get("path") or arguments.get("file_path") or ""
    extras = []
    if "offset" in arguments and arguments["offset"] is not None:
        extras.append(f"offset={arguments['offset']}")
    if "limit" in arguments and arguments["limit"] is not None:
        extras.append(f"limit={arguments['limit']}")
    if extras:
        return f"{path}  ({', '.join(extras)})"
    return str(path)


def _fmt_args_edit(arguments: dict[str, Any]) -> str:
    return str(arguments.get("path") or arguments.get("file_path") or "")


def _fmt_args_write(arguments: dict[str, Any]) -> str:
    path = arguments.get("path") or arguments.get("file_path") or ""
    content = arguments.get("content") or ""
    n_lines = content.count("\n") + 1 if content else 0
    return f"{path}  ({n_lines} lines)" if n_lines else str(path)


def _fmt_args_grep(arguments: dict[str, Any]) -> str:
    pattern = arguments.get("pattern") or arguments.get("query") or ""
    path = arguments.get("path") or arguments.get("dir") or ""
    if path:
        return f"{pattern!r}  in {path}"
    return repr(pattern)


def _fmt_args_glob(arguments: dict[str, Any]) -> str:
    return str(arguments.get("pattern") or arguments.get("path") or "")


def _fmt_args_bash(arguments: dict[str, Any]) -> str:
    return _trunc(str(arguments.get("command", "")), 120)


def _fmt_args_repo_overview(arguments: dict[str, Any]) -> str:
    return str(arguments.get("path") or arguments.get("dir") or ".")


def _fmt_args_webfetch(arguments: dict[str, Any]) -> str:
    return str(arguments.get("url", ""))


def _fmt_args_sub_agent(arguments: dict[str, Any]) -> str:
    agent = arguments.get("agent") or arguments.get("subagent_type") or ""
    desc = arguments.get("description") or arguments.get("prompt") or ""
    pieces = [p for p in (agent, _trunc(str(desc), 80)) if p]
    return "  ".join(pieces)


_ARG_FORMATTERS = {
    "read": _fmt_args_read,
    "edit": _fmt_args_edit,
    "write": _fmt_args_write,
    "grep": _fmt_args_grep,
    "glob": _fmt_args_glob,
    "bash": _fmt_args_bash,
    "repo_overview": _fmt_args_repo_overview,
    "webfetch": _fmt_args_webfetch,
    "sub_agent": _fmt_args_sub_agent,
    "task": _fmt_args_sub_agent,
}


def format_args(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return a 1-line argument summary for the header."""
    if not isinstance(arguments, dict):
        return ""
    fn = _ARG_FORMATTERS.get(tool_name.lower(), _fmt_args_generic)
    try:
        return fn(arguments)
    except Exception:
        return _fmt_args_generic(arguments)


# ── Output formatters ────────────────────────────────────────────────────────

# Each formatter returns a list of plain output lines (no markup). The widget
# renders the first line inline with the header and any additional lines
# beneath it. Return [] for "no output preview".


_HUNK_HEADER_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")


def parse_unified_diff(output: str) -> tuple[str, str, int, int]:
    """Parse a unified-diff string into reconstructed before/after texts.

    Hunks are joined with a single ``…`` separator line (matched on both
    sides) so DiffView treats the gaps as unchanged context rather than
    real changes. Returns ``(before, after, added, removed)``.
    """
    before_parts: list[list[str]] = []
    after_parts: list[list[str]] = []
    cur_before: list[str] = []
    cur_after: list[str] = []
    in_hunk = False
    added = removed = 0

    def flush() -> None:
        nonlocal cur_before, cur_after
        if cur_before or cur_after:
            before_parts.append(cur_before)
            after_parts.append(cur_after)
            cur_before = []
            cur_after = []

    for raw in output.splitlines():
        if raw.startswith("---") or raw.startswith("+++"):
            continue
        if _HUNK_HEADER_RE.match(raw):
            flush()
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            cur_after.append(raw[1:])
            added += 1
        elif raw.startswith("-"):
            cur_before.append(raw[1:])
            removed += 1
        elif raw.startswith(" "):
            cur_before.append(raw[1:])
            cur_after.append(raw[1:])
        elif raw == "":
            cur_before.append("")
            cur_after.append("")
    flush()

    sep = "…"
    before = ("\n" + sep + "\n").join("\n".join(b) for b in before_parts)
    after = ("\n" + sep + "\n").join("\n".join(a) for a in after_parts)
    return before, after, added, removed


def _fmt_out_edit(
    arguments: dict[str, Any], output: str
) -> tuple[list[str], dict[str, Any] | None]:
    """Return (summary_lines, diff_data).

    diff_data, if present, is a dict with keys: path, before, after.
    The widget uses it to mount a DiffView.
    """
    before, after, added, removed = parse_unified_diff(output)
    summary = []
    if added or removed:
        summary.append(f"+{added} -{removed}")

    if not before and not after:
        return summary, None

    path = str(arguments.get("path") or arguments.get("file_path") or "edit")
    return summary, {"path": path, "before": before, "after": after}


def _fmt_out_read(arguments: dict[str, Any], output: str) -> list[str]:
    # No preview — args alone are enough.
    n_lines = output.count("\n") + 1 if output else 0
    return [f"{n_lines} lines"] if n_lines else []


def _fmt_out_write(arguments: dict[str, Any], output: str) -> list[str]:
    return []


def _fmt_out_grep(arguments: dict[str, Any], output: str) -> list[str]:
    if not output.strip():
        return ["0 matches"]
    # Heuristic: count non-empty lines.
    lines = [l for l in output.splitlines() if l.strip()]
    # Some grep outputs include a header like "Found N matches"
    m = re.search(r"(\d+)\s+match(es)?", output, re.IGNORECASE)
    if m:
        return [f"{m.group(1)} matches"]
    return [f"{len(lines)} matches"]


def _fmt_out_glob(arguments: dict[str, Any], output: str) -> list[str]:
    if not output.strip():
        return ["0 files"]
    lines = [l for l in output.splitlines() if l.strip()]
    return [f"{len(lines)} files"]


def _fmt_out_bash(arguments: dict[str, Any], output: str) -> list[str]:
    line = _trunc(output, _MAX_INLINE_LEN)
    return [line] if line else []


def _fmt_out_repo_overview(arguments: dict[str, Any], output: str) -> list[str]:
    # Show tree if compact; otherwise summarize line count.
    lines = output.splitlines()
    if len(lines) <= 15:
        return [l.rstrip() for l in lines if l.strip()]
    return [f"{len(lines)} entries"]


def _fmt_out_generic(arguments: dict[str, Any], output: str) -> list[str]:
    line = _trunc(output, _MAX_INLINE_LEN)
    return [line] if line else []


_OUT_FORMATTERS = {
    "read": _fmt_out_read,
    "write": _fmt_out_write,
    "grep": _fmt_out_grep,
    "glob": _fmt_out_glob,
    "bash": _fmt_out_bash,
    "repo_overview": _fmt_out_repo_overview,
}


def format_output(
    tool_name: str, arguments: dict[str, Any] | None, output: str
) -> dict:
    """Return a dict describing how to render output.

    Keys:
      summary: str   — short text to append after the tool name on header line
      body: list[str] — additional plain-text lines to render under the header
      diff: list[(kind, text)] | None — colored diff lines (edit tool only)
    """
    arguments = arguments or {}
    output = output or ""
    name = tool_name.lower()

    if name == "edit":
        summary_lines, diff_data = _fmt_out_edit(arguments, output)
        summary = summary_lines[0] if summary_lines else ""
        return {
            "summary": summary,
            "body": [],
            "diff": None,
            "diff_view": diff_data,
        }

    fn = _OUT_FORMATTERS.get(name, _fmt_out_generic)
    try:
        lines = fn(arguments, output)
    except Exception:
        lines = _fmt_out_generic(arguments, output)
    summary = lines[0] if lines else ""
    body = lines[1:] if len(lines) > 1 else []
    return {"summary": summary, "body": body, "diff": None, "diff_view": None}


# ── Long-running tool classification ─────────────────────────────────────────

_SLOW_TOOLS = frozenset({"bash", "sub_agent", "task", "webfetch", "repo_overview"})


def is_slow_tool(tool_name: str) -> bool:
    """Tools where users typically wait long enough to want a spinner."""
    return tool_name.lower() in _SLOW_TOOLS
