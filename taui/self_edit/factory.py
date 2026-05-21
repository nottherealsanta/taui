"""Helpers for building self-edit session components."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taui.extensions.builtins import BUILTIN_EXTENSIONS
from taui.self_edit.scoping import (
    PathAllowlist,
    self_edit_roots,
    self_edit_working_dir,
    wrap_tool_with_allowlist,
)
from taui.self_edit.store import SelfEditStore
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.files import ReadTool, WriteTool
from taui.tools.executor import PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "self_edit_system.md"

_SCOPED_TOOL_NAMES = ("read", "edit", "write", "bash")
_SELF_EDIT_BASH_COMMANDS = frozenset({"cat", "find", "grep", "ls", "pwd", "rg"})
_SELF_EDIT_BASH_FORBIDDEN_FIND_ARGS = frozenset({
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
})

_SKILLS_NOTE = (
    "Self-edit can create and modify taui-native skills under "
    "`~/.taui/skills/` or `.taui/skills/`. Agent Skills standard paths "
    "outside those roots remain discoverable by Taui but are outside "
    "self-edit's write scope."
)


@dataclass(frozen=True, slots=True)
class InventoryRow:
    label: str
    builtin_label: str
    global_count: int
    global_path: str
    project_count: int
    project_path: str


@dataclass(frozen=True, slots=True)
class SelfEditInventory:
    active_scope: str
    working_dir: Path
    rows: tuple[InventoryRow, ...]
    fresh: bool
    skills_note: str = _SKILLS_NOTE


@dataclass(slots=True)
class _SelfEditBashTool:
    """Read-only bash facade for self-edit mode."""

    _inner: BashTool

    name: str = "bash"
    description: str = (
        "Run read-only shell inspection commands from the active self-edit scope."
    )
    category: ToolCategory = ToolCategory.SHELL
    guidelines: str = (
        "Use bash only for read-only inspection commands such as `ls`, `grep`, "
        "`find`, `rg`, `cat`, and `pwd`."
    )
    schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.schema = self._inner.schema

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        allowed, reason = _is_self_edit_bash_command_allowed(command)
        if not allowed:
            return ToolResult.fail(f"Self-edit agent: bash is read-only. {reason}")
        return await self._inner.execute(arguments)


def load_self_edit_system_prompt() -> str:
    """Read the static self-edit system prompt body."""
    try:
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "You are the taui self-edit agent. Modify config files directly."


def build_self_edit_system_prompt(working_dir: Path) -> str:
    """Static prompt body prefixed with a live scope/inventory header."""
    inv = collect_self_edit_inventory(working_dir)
    header = _format_inventory_markdown(inv)
    body = load_self_edit_system_prompt()
    return f"{header}\n\n{body}"


def collect_self_edit_inventory(working_dir: Path) -> SelfEditInventory:
    """Scan disk and return the scope inventory used by the prompt and the TUI."""
    home = Path.home()
    active_scope = _safe_active_scope(working_dir)

    rows = (
        InventoryRow(
            label="Agents",
            builtin_label="3 default",
            global_count=_count_agents(home / ".taui" / "agents"),
            global_path="~/.taui/agents/",
            project_count=_count_agents(
                working_dir / ".taui" / "agents"
            ),
            project_path=".taui/agents/",
        ),
        InventoryRow(
            label="Tools / Extensions",
            builtin_label=f"{len(BUILTIN_EXTENSIONS)} (read-only)",
            global_count=_count_py_files(home / ".taui" / "extensions"),
            global_path="~/.taui/extensions/",
            project_count=_count_py_files(working_dir / ".taui" / "extensions"),
            project_path=".taui/extensions/",
        ),
        InventoryRow(
            label="Skills",
            builtin_label="—",
            global_count=_count_skill_dirs(home / ".taui" / "skills"),
            global_path="~/.taui/skills/",
            project_count=_count_skill_dirs(working_dir / ".taui" / "skills"),
            project_path=".taui/skills/",
        ),
        InventoryRow(
            label="MCP servers",
            builtin_label="—",
            global_count=_count_mcp_servers(home / ".taui" / "mcp.toml"),
            global_path="~/.taui/mcp.toml",
            project_count=_count_mcp_servers(working_dir / ".taui" / "mcp.toml"),
            project_path=".taui/mcp.toml",
        ),
        InventoryRow(
            label="Slash commands",
            builtin_label="many (read-only)",
            global_count=_count_py_files(home / ".taui" / "commands"),
            global_path="~/.taui/commands/",
            project_count=_count_py_files(working_dir / ".taui" / "commands"),
            project_path=".taui/commands/",
        ),
    )

    fresh = all(r.global_count == 0 and r.project_count == 0 for r in rows)

    return SelfEditInventory(
        active_scope=active_scope,
        working_dir=working_dir,
        rows=rows,
        fresh=fresh,
    )


def _format_inventory_markdown(inv: SelfEditInventory) -> str:
    active_cwd = self_edit_working_dir(inv.working_dir, inv.active_scope)
    inactive_scope = "project" if inv.active_scope == "global" else "global"
    active_relative_paths = ", ".join(
        f"`{path}`"
        for path in (
            "commands/",
            "extensions/",
            "skills/",
            "agents/",
            "mcp.toml",
        )
    )
    lines = [
        "# Scope & inventory",
        "",
        "Self-edit changes live in one of two **scopes**:",
        "",
        "- **Global** — applies to every project on this machine "
        "(paths under `~/.taui/`).",
        "- **Project** — applies only to the current working directory "
        "(paths under `./.taui/`).",
        "",
        "**Built-ins** (shown first in each table row) ship with taui and "
        "are read-only — you can study them but the registry refuses writes "
        "to source paths. New items you create are saved under the active "
        "scope unless the user specifies otherwise.",
        "",
        f"- Active scope for new agents: **{inv.active_scope}**",
        f"- Project working directory: `{inv.working_dir}`",
        f"- Tool working directory: `{active_cwd}`",
        f"- Relative paths resolve from the **{inv.active_scope}** tool working directory.",
        f"- For active-scope files, use relative paths like {active_relative_paths}.",
        f"- To inspect or edit the inactive **{inactive_scope}** scope, use an absolute path.",
        "",
        "| Category | Built-in | Global | Project |",
        "| --- | --- | --- | --- |",
    ]
    for r in inv.rows:
        lines.append(
            f"| {r.label} | {r.builtin_label} | "
            f"{r.global_count} in `{r.global_path}` | "
            f"{r.project_count} in `{r.project_path}` |"
        )
    lines += ["", inv.skills_note]
    if inv.fresh:
        lines += [
            "",
            "> Fresh install: every global/project count is 0. Built-ins are "
            "the only things that exist yet. The first file you create under "
            "one of the paths above becomes the first item in that scope.",
        ]
    return "\n".join(lines)


def _safe_active_scope(working_dir: Path) -> str:
    try:
        return SelfEditStore(working_dir).load_default_scope()
    except Exception:
        return "global"


def _count_agents(path: Path) -> int:
    if not path.is_dir():
        return 0
    import re
    _id_re = re.compile(r"^[A-Z]{3}$")
    return sum(
        1
        for entry in path.iterdir()
        if entry.is_file() and entry.suffix == ".md" and _id_re.match(entry.stem.upper())
    )


def _count_py_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        1
        for entry in path.iterdir()
        if entry.is_file()
        and entry.suffix == ".py"
        and not entry.name.startswith("_")
    )


def _count_skill_dirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for entry in path.iterdir() if (entry / "SKILL.md").is_file())


def _count_mcp_servers(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return 0
    servers = data.get("servers", {})
    return len(servers) if isinstance(servers, dict) else 0


def _is_self_edit_bash_command_allowed(command: str) -> tuple[bool, str]:
    if not command:
        return False, "Empty command."
    if "$(" in command or any(char in command for char in ";&|<>`"):
        return False, "Shell control operators and redirection are not allowed."
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return False, f"Could not parse command: {exc}."
    if not parts:
        return False, "Empty command."
    executable = Path(parts[0]).name
    if executable not in _SELF_EDIT_BASH_COMMANDS:
        allowed = ", ".join(sorted(_SELF_EDIT_BASH_COMMANDS))
        return False, f"Allowed commands: {allowed}."
    if executable == "find":
        forbidden = _SELF_EDIT_BASH_FORBIDDEN_FIND_ARGS.intersection(parts[1:])
        if forbidden:
            blocked = ", ".join(sorted(forbidden))
            return False, f"`find` arguments are not read-only: {blocked}."
    return True, ""


def _build_self_edit_tools(tool_working_dir: Path) -> dict[str, object]:
    """Fresh self-edit tool instances.

    File tools receive normalized absolute paths from the scoping wrapper, so
    their own workspace is `/`. Bash is the exception: it has no path argument,
    so its process cwd is the active self-edit scope root.
    """
    root = Path("/")
    try:
        tool_working_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return {
        "read": ReadTool(working_dir=root),
        "edit": EditTool(working_dir=root),
        "write": WriteTool(working_dir=root),
        "bash": _SelfEditBashTool(BashTool(working_dir=tool_working_dir)),
    }


def build_scoped_tool_registry(
    base_registry: ToolRegistry,
    project_working_dir: Path | None = None,
    *,
    scope: str | None = None,
) -> ToolRegistry:
    """Return a ToolRegistry with fresh self-edit tools, each path-allowlisted.

    Tools are NOT shared with `base_registry` so the main session's working_dir
    restriction does not leak in and block reads of self-edit config roots.
    """
    project_working_dir = project_working_dir or Path.cwd()
    scope = scope or _safe_active_scope(project_working_dir)
    tool_working_dir = self_edit_working_dir(project_working_dir, scope)
    allowlist = PathAllowlist(self_edit_roots(project_working_dir))
    scoped = ToolRegistry()
    for name, tool in _build_self_edit_tools(tool_working_dir).items():
        scoped._tools[name] = wrap_tool_with_allowlist(
            tool,
            allowlist,
            relative_root=tool_working_dir,
        )
    return scoped


def build_self_edit_executor(
    base_registry: ToolRegistry,
    base_executor: ToolExecutor,
    project_working_dir: Path | None = None,
) -> ToolExecutor:
    """Build a ToolExecutor scoped to self-edit tools with no approval prompts."""
    registry = build_scoped_tool_registry(base_registry, project_working_dir)
    policy = ToolPolicy({name: PolicyDecision.AUTO for name in registry.names})
    return ToolExecutor(
        registry=registry,
        policy=policy,
        timeout=base_executor._timeout,
    )
