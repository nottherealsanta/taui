"""Simulator: pretends the user has already added stuff to taui's global scope.

Running this script drops four files into ``~/.taui/`` so the next
taui session looks like a user who had spent time customizing their
setup — adding a tool, an agent, a prompt, and a skill. Each file
lives in the directory taui's self-edit inventory expects for that
*kind* of contribution, so they show up under the right category in
the self-edit modal rather than all collapsing into "tools".

What it drops:

  ~/.taui/agents/ASK.md             — agent profile (frontmatter +
      system prompt). A read-only Q&A agent, scoped to read/glob/grep,
      that refuses to mutate anything.

  ~/.taui/prompts/worktree.md       — standalone prompt file. Verbose
      multi-paragraph instruction telling the agent to open an
      isolated git worktree before solving anything.

  ~/.taui/skills/textual/SKILL.md   — skill package; taui's
      SkillRegistry picks it up from the global skill dir.

  ~/.taui/extensions/notebook.py    — extension that registers the
      ``notebook`` tool group: ``notebook_read``, ``notebook_edit``,
      ``notebook_run_cell``, and ``notebook_clear`` all declare
      ``group = "notebook"`` and therefore appear together in taui's
      tools tree, allowed-tools toggle grid, and context banner.

After running, restart taui and the four contributions appear as if
they had always been there.
"""

from __future__ import annotations

import sys
from pathlib import Path

TAUI_HOME = Path.home() / ".taui"
AGENTS_DIR = TAUI_HOME / "agents"
PROMPTS_DIR = TAUI_HOME / "prompts"
SKILLS_DIR = TAUI_HOME / "skills"
EXTENSIONS_DIR = TAUI_HOME / "extensions"


# --------------------------------------------------------------------------- #
# Agent: ASK (read-only Q&A) — ~/.taui/agents/ASK.md                          #
# --------------------------------------------------------------------------- #

ASK_AGENT_MD = '''\
---
name: ASK
usage: both
color: "#7dcfff"
allowed_tools: ["read", "glob", "grep"]
---
You are ASK, a strictly read-only assistant. Your sole job is to
answer the user's question by reading and searching the codebase.

You MUST NOT call any tool that writes, edits, executes shell
commands, or mutates state in any way. If answering would require
modification, refuse and explain what change *would* be needed
instead.

Cite file paths and line numbers for every claim
(e.g. ``src/foo.py:42``). Prefer concrete references over prose.
Stop as soon as you have answered — do not pad.
'''


# --------------------------------------------------------------------------- #
# Prompt: worktree — ~/.taui/prompts/worktree.md                              #
# --------------------------------------------------------------------------- #

WORKTREE_PROMPT_MD = """\
Open a worktree to solve this
"""


# --------------------------------------------------------------------------- #
# Skill: textual — ~/.taui/skills/textual/SKILL.md                            #
# --------------------------------------------------------------------------- #

TEXTUAL_SKILL_MD = """\
---
name: textual
description: Build Textual TUIs — widgets, reactivity, CSS, async event handling.
---

# Textual

Use this skill when working on a Python TUI built with
[Textual](https://textual.textualize.io).

## Core concepts

- **App / Screen / Widget** form the composition tree. Mount widgets
  with `compose()`; query them with `self.query_one(selector)`.
- **Reactivity**: declare `reactive(default)` class attributes; mutate
  them and Textual repaints. Use `watch_<name>()` for side effects.
- **Messages & events**: subclass `Message` for custom signals; handle
  with `on_<message_class>` or the `@on(Selector)` decorator.
- **CSS**: prefer Textual CSS files (`CSS_PATH = "app.tcss"`) over
  inline styles. Selectors mirror the widget tree.
- **Workers**: never block the event loop. Wrap blocking work in
  `@work(thread=True)` or `await` an async helper.

## Common pitfalls

- Do not call `await` inside `compose()` — it is synchronous.
- `query_one` raises if zero or multiple match; use `query` for
  collections.
- Reactive defaults are shared across instances if mutable — wrap in
  a factory.

## When you are asked to add a widget

1. Subclass the closest existing widget (e.g. `Static`, `Container`).
2. Add a `DEFAULT_CSS` block or a selector in the app's `.tcss` file.
3. Wire events with `@on(...)` rather than long `if isinstance` chains.
4. Update tests with `pilot.press(...)` and `pilot.click(...)`.
"""


# --------------------------------------------------------------------------- #
# Tool group: notebook — ~/.taui/extensions/notebook.py                       #
# --------------------------------------------------------------------------- #
#                                                                             #
# Demonstrates the tool-group concept: four tools (notebook_read,             #
# notebook_edit, notebook_run_cell, notebook_clear) all declare               #
# ``group = "notebook"``, so the self-edit UI and context banner show them    #
# together under one folder/pill. taui's defaults no longer ship notebook     #
# tooling, so this is the user's way of opting back in — and of using a      #
# group for it.                                                               #

NOTEBOOK_EXT_PY = '''\
"""User-added extension: the ``notebook`` tool group.

Four sibling tools — notebook_read, notebook_edit, notebook_run_cell, and
notebook_clear — that all declare ``group = "notebook"`` so taui shows them
together in the agent toggle grid, the tools tree, and the context banner.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult

NOTEBOOK_GROUP = "notebook"


def _load_notebook(
    working_dir: Path, path_str: str
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]] | str:
    """Resolve the path, parse the notebook, and return (path, nb, cells).

    Returns an error string on failure so callers can short-circuit.
    """
    if not path_str:
        return "path is required"
    path = Path(path_str)
    if not path.is_absolute():
        path = working_dir / path
    if not path.exists():
        return f"File not found: {path}"
    if path.suffix != ".ipynb":
        return f"Not a notebook file: {path}"
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return f"Failed to read notebook: {exc}"
    cells = nb.get("cells", [])
    if not isinstance(cells, list):
        return "Malformed notebook: cells is not a list"
    return path, nb, cells


def _cell_source(cell: dict[str, Any]) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return str(src)


def _write_notebook(path: Path, nb: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(nb, indent=1, ensure_ascii=False) + "\\n",
        encoding="utf-8",
    )


# ── notebook_read ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class NotebookReadTool:
    """List cells in a Jupyter notebook (and optionally show their source)."""

    name: str = "notebook_read"
    description: str = (
        "Read a Jupyter notebook (.ipynb): list cells with index, type, and "
        "a preview of source. Set `full: true` to dump every cell\\'s full "
        "source. Use this before notebook_edit / notebook_run_cell to figure "
        "out which cell to target."
    )
    category: ToolCategory = ToolCategory.FILE_READ
    group: str = NOTEBOOK_GROUP
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file.",
                    },
                    "full": {
                        "type": "boolean",
                        "description": (
                            "If true, include each cell\\'s full source "
                            "(default false: 1-line preview only)."
                        ),
                    },
                },
                "required": ["path"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        loaded = _load_notebook(
            self.working_dir, arguments.get("path", "")
        )
        if isinstance(loaded, str):
            return ToolResult.fail(loaded)
        path, _nb, cells = loaded
        full = bool(arguments.get("full", False))

        if not cells:
            return ToolResult.ok(f"{path} has 0 cells.")

        lines = [f"{path} — {len(cells)} cells"]
        for idx, cell in enumerate(cells):
            ctype = cell.get("cell_type", "?")
            source = _cell_source(cell)
            if full:
                lines.append(f"\\n--- [{idx}] {ctype} ---")
                lines.append(source.rstrip())
            else:
                preview = source.splitlines()[0] if source else ""
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"  [{idx}] {ctype:8s}  {preview}")
        return ToolResult.ok("\\n".join(lines))


# ── notebook_edit ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class NotebookEditTool:
    """Edit Jupyter notebook cells by index."""

    name: str = "notebook_edit"
    description: str = (
        "Edit a Jupyter notebook (.ipynb) cell by index. "
        "Can replace cell source, insert new cells, or delete cells."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    group: str = NOTEBOOK_GROUP
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file.",
                    },
                    "cell_index": {
                        "type": "integer",
                        "description": (
                            "0-based index of the cell to edit/delete, "
                            "or insertion point."
                        ),
                    },
                    "action": {
                        "type": "string",
                        "enum": ["replace", "insert", "delete"],
                        "description": (
                            "Action: replace cell content, insert new "
                            "cell, or delete cell."
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": "New cell source (required for replace/insert).",
                    },
                    "cell_type": {
                        "type": "string",
                        "enum": ["code", "markdown", "raw"],
                        "description": "Cell type for insert (default: code).",
                    },
                },
                "required": ["path", "cell_index", "action"],
                "additionalProperties": False,
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        loaded = _load_notebook(
            self.working_dir, arguments.get("path", "")
        )
        if isinstance(loaded, str):
            return ToolResult.fail(loaded)
        path, nb, cells = loaded

        cell_index = arguments.get("cell_index")
        if cell_index is None:
            return ToolResult.fail("cell_index is required")
        action = arguments.get("action", "")
        source = arguments.get("source", "")
        cell_type = arguments.get("cell_type", "code")
        if action not in ("replace", "insert", "delete"):
            return ToolResult.fail(f"Unknown action: {action}")

        if action == "delete":
            if cell_index < 0 or cell_index >= len(cells):
                return ToolResult.fail(
                    f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
                )
            removed = cells.pop(cell_index)
            removed_type = removed.get("cell_type", "unknown")
            _write_notebook(path, nb)
            return ToolResult.ok(
                f"Deleted {removed_type} cell at index {cell_index}. "
                f"Notebook now has {len(cells)} cells."
            )

        if action in ("replace", "insert") and source is None:
            return ToolResult.fail(f"source is required for {action}")

        source_lines = source.split("\\n") if source else [""]
        formatted = [line + "\\n" for line in source_lines[:-1]]
        if source_lines:
            formatted.append(source_lines[-1])

        if action == "replace":
            if cell_index < 0 or cell_index >= len(cells):
                return ToolResult.fail(
                    f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
                )
            cells[cell_index]["source"] = formatted
            _write_notebook(path, nb)
            return ToolResult.ok(
                f"Replaced cell {cell_index} source ({len(source_lines)} lines)."
            )

        if cell_index < 0 or cell_index > len(cells):
            return ToolResult.fail(
                f"cell_index {cell_index} out of range for insert (0..{len(cells)})"
            )
        new_cell: dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": formatted,
        }
        if cell_type == "code":
            new_cell["execution_count"] = None
            new_cell["outputs"] = []
        cells.insert(cell_index, new_cell)
        _write_notebook(path, nb)
        return ToolResult.ok(
            f"Inserted {cell_type} cell at index {cell_index}. "
            f"Notebook now has {len(cells)} cells."
        )


# ── notebook_run_cell ─────────────────────────────────────────────────────


@dataclass(slots=True)
class NotebookRunCellTool:
    """Execute a single code cell\\'s source via a subprocess and capture output.

    Lightweight by design: spawns ``python -c <source>`` so the runner has no
    extra dependencies. State is *not* shared across calls — each invocation
    starts a fresh interpreter. For true kernel semantics use jupyter directly.
    """

    name: str = "notebook_run_cell"
    description: str = (
        "Run a single code cell from a Jupyter notebook in a fresh Python "
        "subprocess and return stdout/stderr. State is not preserved across "
        "calls. Use for quick sanity checks; spin up a real Jupyter kernel for "
        "stateful workflows."
    )
    category: ToolCategory = ToolCategory.SHELL
    group: str = NOTEBOOK_GROUP
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)
    timeout: int = 30

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file.",
                    },
                    "cell_index": {
                        "type": "integer",
                        "description": "0-based index of the code cell to run.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Seconds before the subprocess is killed. Default 30.",
                    },
                },
                "required": ["path", "cell_index"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        loaded = _load_notebook(
            self.working_dir, arguments.get("path", "")
        )
        if isinstance(loaded, str):
            return ToolResult.fail(loaded)
        path, _nb, cells = loaded

        cell_index = arguments.get("cell_index")
        if cell_index is None:
            return ToolResult.fail("cell_index is required")
        if cell_index < 0 or cell_index >= len(cells):
            return ToolResult.fail(
                f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
            )
        cell = cells[cell_index]
        if cell.get("cell_type") != "code":
            return ToolResult.fail(
                f"Cell {cell_index} is a "
                f"{cell.get('cell_type', '?')} cell, not code."
            )

        source = _cell_source(cell)
        if not source.strip():
            return ToolResult.ok("(cell is empty)")

        timeout = int(arguments.get("timeout", self.timeout))
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", source,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(path.parent),
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            return ToolResult.fail(
                f"Cell {cell_index} timed out after {timeout}s"
            )
        except OSError as exc:
            return ToolResult.fail(f"Failed to run cell: {exc}")

        text = (stdout or b"").decode("utf-8", errors="replace")
        if len(text) > 8000:
            text = text[:8000] + "\\n… (truncated)"
        exit_code = proc.returncode or 0
        header = (
            f"cell {cell_index} · exit {exit_code} · "
            f"{path.name}"
        )
        body = text.rstrip() if text else "(no output)"
        return ToolResult.ok(
            f"{header}\\n{body}",
            cell_index=cell_index,
            exit_code=exit_code,
        )


# ── notebook_clear ────────────────────────────────────────────────────────


@dataclass(slots=True)
class NotebookClearTool:
    """Strip outputs (and execution counts) from a notebook\\'s code cells."""

    name: str = "notebook_clear"
    description: str = (
        "Clear all outputs and reset execution counts on every code cell in "
        "a notebook. Useful before committing — large output payloads should "
        "not live in source control."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    group: str = NOTEBOOK_GROUP
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file.",
                    },
                },
                "required": ["path"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        loaded = _load_notebook(
            self.working_dir, arguments.get("path", "")
        )
        if isinstance(loaded, str):
            return ToolResult.fail(loaded)
        path, nb, cells = loaded

        cleared = 0
        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            if cell.get("outputs") or cell.get("execution_count") is not None:
                cleared += 1
            cell["outputs"] = []
            cell["execution_count"] = None
        _write_notebook(path, nb)
        return ToolResult.ok(
            f"Cleared outputs on {cleared} code cell(s) in {path}."
        )


# ── register ──────────────────────────────────────────────────────────────


def register(ctx):
    if ctx.tools is None:
        return
    for tool in (
        NotebookReadTool(),
        NotebookEditTool(),
        NotebookRunCellTool(),
        NotebookClearTool(),
    ):
        ctx.tools.register_or_replace(tool)
'''


# --------------------------------------------------------------------------- #
# Installer                                                                   #
# --------------------------------------------------------------------------- #

FILES = [
    (AGENTS_DIR / "ASK.md",                       ASK_AGENT_MD),
    (PROMPTS_DIR / "worktree.md",                 WORKTREE_PROMPT_MD),
    (SKILLS_DIR / "textual" / "SKILL.md",         TEXTUAL_SKILL_MD),
    (EXTENSIONS_DIR / "notebook.py",              NOTEBOOK_EXT_PY),
]


def install() -> list[Path]:
    written: list[Path] = []
    for dest, content in FILES:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(dest)
    return written


def uninstall() -> list[Path]:
    removed: list[Path] = []
    # Include legacy paths from earlier installs so 'uninstall' is idempotent
    # across the rename from notebook_edit.py to notebook.py.
    legacy_paths = [EXTENSIONS_DIR / "notebook_edit.py"]
    for dest, _ in FILES:
        if dest.exists():
            dest.unlink()
            removed.append(dest)
    for legacy in legacy_paths:
        if legacy.exists():
            legacy.unlink()
            removed.append(legacy)
    # Tidy now-empty directories we created.
    for d in (
        SKILLS_DIR / "textual",
        PROMPTS_DIR,
        AGENTS_DIR,
    ):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "install"
    if cmd in ("install", "i"):
        for p in install():
            print(f"wrote: {p}")
        print()
        print("Restart taui to pick up the user-added contributions.")
        return 0
    if cmd in ("uninstall", "u", "remove", "rm"):
        for p in uninstall():
            print(f"removed: {p}")
        return 0
    print(f"unknown command: {cmd!r}; use 'install' or 'uninstall'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
