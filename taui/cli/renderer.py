"""Rich rendering helpers — convert Rich objects to plain or ANSI strings."""

from __future__ import annotations

import io
import shutil

from rich.console import Console


def term_width() -> int:
    """Get the current terminal width."""
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def render_rich(*args, **kwargs) -> str:
    """Render Rich objects to plain string (no ANSI — we use pt styles)."""
    buf = io.StringIO()
    c = Console(
        file=buf, highlight=False,
        force_terminal=False, no_color=True, width=term_width(),
    )
    c.print(*args, **kwargs)
    return buf.getvalue().rstrip("\n")


def render_rich_ansi(*args, **kwargs) -> str:
    """Render Rich objects to ANSI string for the output buffer."""
    buf = io.StringIO()
    c = Console(
        file=buf, highlight=False,
        force_terminal=True, width=term_width(),
    )
    c.print(*args, **kwargs)
    return buf.getvalue().rstrip("\n")


def format_args(name: str, arguments: dict) -> str:
    """Format tool arguments for display — compact and readable."""
    if not arguments:
        return ""
    match name:
        case "read":
            return arguments.get("path", "")
        case "write":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            lines = content.count("\n") + (1 if content else 0)
            return f"{path}, {lines} lines"
        case "edit":
            path = arguments.get("path", "")
            edits = arguments.get("edits", [])
            count = len(edits) if isinstance(edits, list) else "?"
            return f"{path}, {count} edit{'s' if count != 1 else ''}"
        case "glob":
            return arguments.get("pattern", "")
        case "grep":
            pat = arguments.get("pattern", "")
            inc = arguments.get("include", "")
            return f"/{pat}/" + (f" {inc}" if inc else "")
        case "bash":
            cmd = arguments.get("command", "")
            if len(cmd) > 80:
                cmd = cmd[:77] + "..."
            return cmd
        case "git":
            op = arguments.get("operation", "")
            args = arguments.get("args", {})
            if args:
                details = ", ".join(f"{k}={v}" for k, v in args.items())
                return f"{op} ({details})"
            return op
        case "question":
            q = arguments.get("question", "")
            if len(q) > 60:
                q = q[:57] + "..."
            return q
        case "sub_agent":
            task = arguments.get("task", "")
            if len(task) > 60:
                task = task[:57] + "..."
            tools = arguments.get("tools")
            if tools:
                return f"{task} [{', '.join(tools)}]"
            return task
        case "skills":
            op = arguments.get("operation", "")
            skill = arguments.get("skill", "")
            return f"{op} {skill}".strip()
        case "mcp":
            op = arguments.get("operation", "")
            server = arguments.get("server", "")
            tool = arguments.get("tool", "")
            parts = [op]
            if server:
                parts.append(server)
            if tool:
                parts.append(tool)
            return " ".join(parts)
        case _:
            parts = []
            for k, v in arguments.items():
                sv = str(v)
                if len(sv) > 40:
                    sv = sv[:37] + "..."
                parts.append(f"{k}={sv}")
            return ", ".join(parts)
