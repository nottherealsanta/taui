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

  ~/.taui/extensions/notebook_edit.py — extension that registers the
      ``notebook_edit`` tool. taui's defaults no longer ship it, so
      this is the user's way of opting back in.

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
# Tool: notebook_edit — ~/.taui/extensions/notebook_edit.py                   #
# --------------------------------------------------------------------------- #

NOTEBOOK_EDIT_EXT_PY = '''\
"""User-added extension: ``notebook_edit`` tool.

The taui defaults no longer register this tool, so the user has opted
back in by dropping this file into ``~/.taui/extensions/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class NotebookEditTool:
    """Edit Jupyter notebook cells by index."""

    name: str = "notebook_edit"
    description: str = (
        "Edit a Jupyter notebook (.ipynb) cell by index. "
        "Can replace cell source, insert new cells, or delete cells."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file",
                    },
                    "cell_index": {
                        "type": "integer",
                        "description": (
                            "0-based index of the cell to edit/delete, "
                            "or insertion point"
                        ),
                    },
                    "action": {
                        "type": "string",
                        "enum": ["replace", "insert", "delete"],
                        "description": (
                            "Action: replace cell content, insert new "
                            "cell, or delete cell"
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": "New cell source (required for replace/insert)",
                    },
                    "cell_type": {
                        "type": "string",
                        "enum": ["code", "markdown", "raw"],
                        "description": "Cell type for insert (default: code)",
                    },
                },
                "required": ["path", "cell_index", "action"],
                "additionalProperties": False,
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path_str = arguments.get("path", "")
        cell_index = arguments.get("cell_index")
        action = arguments.get("action", "")
        source = arguments.get("source", "")
        cell_type = arguments.get("cell_type", "code")

        if not path_str:
            return ToolResult.fail("path is required")
        if cell_index is None:
            return ToolResult.fail("cell_index is required")
        if action not in ("replace", "insert", "delete"):
            return ToolResult.fail(f"Unknown action: {action}")

        path = Path(path_str)
        if not path.is_absolute():
            path = self.working_dir / path

        if not path.exists():
            return ToolResult.fail(f"File not found: {path}")
        if path.suffix != ".ipynb":
            return ToolResult.fail(f"Not a notebook file: {path}")

        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ToolResult.fail(f"Failed to read notebook: {exc}")

        cells = nb.get("cells", [])

        if action == "delete":
            if cell_index < 0 or cell_index >= len(cells):
                return ToolResult.fail(
                    f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
                )
            removed = cells.pop(cell_index)
            removed_type = removed.get("cell_type", "unknown")
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\\n")
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
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\\n")
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
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\\n")
        return ToolResult.ok(
            f"Inserted {cell_type} cell at index {cell_index}. "
            f"Notebook now has {len(cells)} cells."
        )


def register(ctx):
    if ctx.tools is not None:
        ctx.tools.register_or_replace(NotebookEditTool())
'''


# --------------------------------------------------------------------------- #
# Installer                                                                   #
# --------------------------------------------------------------------------- #

FILES = [
    (AGENTS_DIR / "ASK.md",                       ASK_AGENT_MD),
    (PROMPTS_DIR / "worktree.md",                 WORKTREE_PROMPT_MD),
    (SKILLS_DIR / "textual" / "SKILL.md",         TEXTUAL_SKILL_MD),
    (EXTENSIONS_DIR / "notebook_edit.py",         NOTEBOOK_EDIT_EXT_PY),
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
    for dest, _ in FILES:
        if dest.exists():
            dest.unlink()
            removed.append(dest)
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
