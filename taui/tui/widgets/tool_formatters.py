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
    offset = arguments.get("offset")
    if offset is not None:
        extras.append(f"offset={offset}")
    limit = arguments.get("limit")
    if limit is not None:
        extras.append(f"limit={limit}")
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
    desc = (
        arguments.get("task")
        or arguments.get("description")
        or arguments.get("prompt")
        or ""
    )
    pieces = [p for p in (agent, _trunc(str(desc), 80)) if p]
    return "  ".join(pieces)


def _fmt_args_git(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or ""
    args = arguments.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    extras: list[str] = []
    if op in ("diff",):
        if args.get("staged"):
            extras.append("--staged")
        ref = args.get("ref")
        if isinstance(ref, str) and ref:
            extras.append(ref)
        file = args.get("file")
        if isinstance(file, str) and file:
            extras.append(file)
    elif op in ("log",):
        count = args.get("count")
        if isinstance(count, int):
            extras.append(f"-{count}")
        file = args.get("file")
        if isinstance(file, str) and file:
            extras.append(file)
    elif op in ("show", "checkout"):
        ref = args.get("ref")
        if isinstance(ref, str) and ref:
            extras.append(ref)
    elif op == "blame":
        file = args.get("file")
        if isinstance(file, str) and file:
            extras.append(file)
        s, e = args.get("line_start"), args.get("line_end")
        if isinstance(s, int):
            extras.append(f"L{s}-{e}" if isinstance(e, int) else f"L{s}+")
    elif op == "commit":
        msg = args.get("message")
        if isinstance(msg, str) and msg:
            extras.append(_trunc(msg, 60))
    elif op == "add":
        files = args.get("files")
        if isinstance(files, list):
            extras.append(_trunc(" ".join(str(f) for f in files), 60))
        elif isinstance(files, str):
            extras.append(_trunc(files, 60))
        else:
            extras.append("-A")
    elif op in ("stash_push",):
        msg = args.get("message")
        if isinstance(msg, str) and msg:
            extras.append(_trunc(msg, 60))
    if extras:
        return f"{op}  {' '.join(extras)}"
    return op or ""


def _fmt_args_task(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or "list"
    extras: list[str] = []
    if op == "add":
        title = arguments.get("title")
        if isinstance(title, str) and title:
            extras.append(_trunc(title, 60))
    elif op == "update":
        tid = arguments.get("task_id")
        if tid:
            extras.append(f"#{tid}")
        status = arguments.get("status")
        if status:
            extras.append(f"→{status}")
    elif op in ("complete", "remove"):
        tid = arguments.get("task_id")
        if tid:
            extras.append(f"#{tid}")
    return f"{op}  {' '.join(extras)}" if extras else op


def _fmt_args_memory(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or ""
    key = arguments.get("key")
    if op == "save" and key:
        content = arguments.get("content") or ""
        n_lines = content.count("\n") + 1 if content else 0
        return f"{op}  {key}  ({n_lines} lines)" if n_lines else f"{op}  {key}"
    if key:
        return f"{op}  {key}"
    return op


def _fmt_args_skills(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or ""
    skill = arguments.get("skill")
    return f"{op}  {skill}" if skill else op


def _fmt_args_worktree(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or ""
    extras: list[str] = []
    branch = arguments.get("branch")
    if isinstance(branch, str) and branch:
        extras.append(branch)
    base = arguments.get("base")
    if isinstance(base, str) and base:
        extras.append(f"from {base}")
    if op == "exit" and arguments.get("keep"):
        extras.append("--keep")
    return f"{op}  {' '.join(extras)}" if extras else op


def _fmt_args_mcp(arguments: dict[str, Any]) -> str:
    op = arguments.get("operation") or ""
    server = arguments.get("server")
    tool = arguments.get("tool")
    if op == "call" and server and tool:
        return f"{op}  {server}/{tool}"
    if server:
        return f"{op}  {server}"
    return op


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
    "git": _fmt_args_git,
    "task": _fmt_args_task,
    "memory": _fmt_args_memory,
    "skills": _fmt_args_skills,
    "worktree": _fmt_args_worktree,
    "mcp": _fmt_args_mcp,
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
) -> tuple[int, int, dict[str, Any] | None]:
    """Return (added, removed, diff_data).

    diff_data, if present, is a dict with keys: path, before, after.
    The widget uses it to mount a DiffView.
    """
    before, after, added, removed = parse_unified_diff(output)

    if not before and not after:
        return added, removed, None

    path = str(arguments.get("path") or arguments.get("file_path") or "edit")
    return added, removed, {"path": path, "before": before, "after": after}


def _fmt_out_read(arguments: dict[str, Any], output: str) -> list[str]:
    # No preview — args (limit) alone are enough.
    return []


def _fmt_out_write(arguments: dict[str, Any], output: str) -> list[str]:
    return []


def _fmt_out_grep(arguments: dict[str, Any], output: str) -> list[str]:
    if not output.strip():
        return ["no matches"]
    lines = [ln for ln in output.splitlines() if ln.strip()]
    m = re.search(r"(\d+)\s+match(es)?", output, re.IGNORECASE)
    n = int(m.group(1)) if m else len(lines)
    files = len({ln.split(":", 1)[0] for ln in lines if ":" in ln})
    if files > 1:
        return [f"{n} matches in {files} files"]
    return [f"{n} match" + ("es" if n != 1 else "")]


def _fmt_out_glob(arguments: dict[str, Any], output: str) -> list[str]:
    if not output.strip():
        return ["no files"]
    lines = [ln for ln in output.splitlines() if ln.strip()]
    n = len(lines)
    return [f"{n} file" + ("s" if n != 1 else "")]


def _fmt_out_bash(arguments: dict[str, Any], output: str) -> list[str]:
    # Inline preview falls back to a 1-line tail; full output is in the modal.
    line = _trunc(output, _MAX_INLINE_LEN)
    return [line] if line else []


def _fmt_out_repo_overview(arguments: dict[str, Any], output: str) -> list[str]:
    lines = output.splitlines()
    if len(lines) <= 15:
        return [ln.rstrip() for ln in lines if ln.strip()]
    return [f"{len(lines)} entries"]


def _fmt_out_webfetch(arguments: dict[str, Any], output: str) -> list[str]:
    if not output.strip():
        return []
    lines = output.splitlines()
    n_bytes = len(output)
    return [f"{len(lines)} lines, {n_bytes:,} bytes"]


def _fmt_out_git(arguments: dict[str, Any], output: str) -> list[str]:
    op = (arguments or {}).get("operation") or ""
    text = output or ""
    if not text.strip():
        return ["(empty)"]

    if op == "status":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines or "working tree clean" in text.lower():
            return ["clean"]
        # Porcelain v1: 2-char status code + space + filepath
        added = modified = deleted = renamed = untracked = 0
        for ln in lines:
            if len(ln) < 3:
                continue
            code = ln[:2]
            if "?" in code:
                untracked += 1
            elif "A" in code:
                added += 1
            elif "D" in code:
                deleted += 1
            elif "R" in code:
                renamed += 1
            elif "M" in code or code.strip():
                modified += 1
        parts = []
        if modified:
            parts.append(f"~{modified}")
        if added:
            parts.append(f"+{added}")
        if deleted:
            parts.append(f"-{deleted}")
        if renamed:
            parts.append(f"→{renamed}")
        if untracked:
            parts.append(f"?{untracked}")
        summary = " ".join(parts) or f"{len(lines)} changes"
        out = [summary]
        for ln in lines[:5]:
            out.append(ln)
        if len(lines) > 5:
            out.append(f"… {len(lines) - 5} more")
        return out

    if op == "diff":
        added = len(re.findall(r"^\+[^+]", text, re.MULTILINE))
        removed = len(re.findall(r"^-[^-]", text, re.MULTILINE))
        files = len(re.findall(r"^diff --git", text, re.MULTILINE))
        hunks = len(re.findall(r"^@@", text, re.MULTILINE))
        if not (added or removed or files):
            return ["no changes"]
        parts = [f"{files} file" + ("s" if files != 1 else "")]
        if hunks:
            parts.append(f"{hunks} hunk" + ("s" if hunks != 1 else ""))
        parts.append(f"+{added}")
        parts.append(f"-{removed}")
        return [" · ".join(parts)]

    if op == "log":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        head = lines[:5]
        tail = (
            [f"… {len(lines) - 5} more"] if len(lines) > 5 else []
        )
        return head + tail

    if op == "branch_current":
        return [text.strip() or "(detached)"]

    if op == "branch_list":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        cur = next((ln for ln in lines if ln.startswith("*")), "")
        n = len(lines)
        out = [f"{n} branch" + ("es" if n != 1 else "")]
        if cur:
            out.append(cur.strip())
        return out

    if op == "stash_list":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return ["no stashes"]
        return [f"{len(lines)} stash" + ("es" if len(lines) != 1 else "")]

    if op in ("commit", "add", "checkout", "stash_push", "stash_pop", "show", "blame"):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        head = lines[:6]
        if len(lines) > 6:
            head.append(f"… {len(lines) - 6} more")
        return head

    # Fallback
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 5:
        return lines
    return lines[:5] + [f"… {len(lines) - 5} more"]


def _fmt_out_generic(arguments: dict[str, Any], output: str) -> list[str]:
    line = _trunc(output, _MAX_INLINE_LEN)
    return [line] if line else []


def _fmt_out_task(arguments: dict[str, Any], output: str) -> list[str]:
    op = (arguments or {}).get("operation") or "list"
    text = output or ""
    if not text.strip():
        return ["(no tasks)"]

    if op == "list":
        # Count status icons in the listing produced by the tool.
        counts = {
            "pending": text.count("⬜"),
            "in_progress": text.count("🔄"),
            "completed": text.count("✅"),
            "cancelled": text.count("❌"),
        }
        parts = [f"{v} {k}" for k, v in counts.items() if v]
        total = sum(counts.values())
        if total:
            return [f"{total} task" + ("s" if total != 1 else ""),
                    " · ".join(parts)]
        return [text.splitlines()[0]] if text.splitlines() else []

    # add/update/complete/remove/clear return a one-line result.
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return [first] if first else []


def _fmt_out_memory(arguments: dict[str, Any], output: str) -> list[str]:
    op = (arguments or {}).get("operation") or ""
    text = output or ""
    if not text.strip():
        return []
    if op == "list":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        n = len(lines)
        return [f"{n} entries" if n != 1 else "1 entry"]
    if op == "read":
        lines = text.splitlines()
        return [f"{len(lines)} lines, {len(text):,} bytes"]
    # save/delete: first non-empty line is the success message.
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return [first] if first else []


def _fmt_out_skills(arguments: dict[str, Any], output: str) -> list[str]:
    op = (arguments or {}).get("operation") or ""
    text = output or ""
    if not text.strip():
        return []
    if op in ("list", "status"):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        head = lines[:6]
        if len(lines) > 6:
            head.append(f"… {len(lines) - 6} more")
        return head
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return [first] if first else []


def _fmt_out_worktree(arguments: dict[str, Any], output: str) -> list[str]:
    text = output or ""
    if not text.strip():
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = lines[:4]
    if len(lines) > 4:
        head.append(f"… {len(lines) - 4} more")
    return head


def _fmt_out_mcp(arguments: dict[str, Any], output: str) -> list[str]:
    op = (arguments or {}).get("operation") or ""
    text = output or ""
    if not text.strip():
        return []
    if op in ("servers", "tools"):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        n = len(lines)
        label = "server" if op == "servers" else "tool"
        return [f"{n} {label}" + ("s" if n != 1 else "")]
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return [_trunc(first, _MAX_INLINE_LEN)] if first else []


_OUT_FORMATTERS = {
    "read": _fmt_out_read,
    "write": _fmt_out_write,
    "grep": _fmt_out_grep,
    "glob": _fmt_out_glob,
    "bash": _fmt_out_bash,
    "repo_overview": _fmt_out_repo_overview,
    "webfetch": _fmt_out_webfetch,
    "git": _fmt_out_git,
    "task": _fmt_out_task,
    "memory": _fmt_out_memory,
    "skills": _fmt_out_skills,
    "worktree": _fmt_out_worktree,
    "mcp": _fmt_out_mcp,
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
        added, removed, diff_data = _fmt_out_edit(arguments, output)
        return {
            "summary": "",
            "body": [],
            "diff": None,
            "diff_view": diff_data,
            "edit_stats": (added, removed),
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
