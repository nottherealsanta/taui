from __future__ import annotations

from pathlib import Path

from taui.tools.base import ToolContext, ToolResult


def resolve_path(context: ToolContext, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = context.working_dir / candidate
    resolved = candidate.resolve()
    workspace = context.working_dir.resolve()
    if not _is_within(workspace, resolved):
        raise ValueError(f"Path '{resolved}' is outside workspace '{workspace}'.")
    return resolved


def format_numbered_lines(lines: list[str], start_line: int) -> str:
    rendered: list[str] = []
    for index, line in enumerate(lines, start=start_line):
        rendered.append(f"{index:05d}| {line}")
    return "\n".join(rendered)


def normalize_tool_error(
    message: str, metadata: dict[str, object] | None = None
) -> ToolResult:
    return ToolResult.fail(message, metadata=metadata)


def _is_within(root: Path, child: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False
