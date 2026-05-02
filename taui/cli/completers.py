"""Completers for the CLI input buffer."""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

from taui.commands.registry import CommandRegistry


class SlashCompleter(Completer):
    """Auto-complete slash commands and their subcommands."""

    _SUBCOMMANDS: dict[str, list[str]] = {
        "/model": ["list", "ls", "refresh", "select"],
        "/provider": ["copilot", "codex"],
        "/sessions": [],
    }

    def __init__(self, registry: CommandRegistry, get_session=None) -> None:
        self._registry = registry
        self._get_session = get_session

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        cmd = parts[0]

        if len(parts) == 1 and not text.endswith(" "):
            for name in self._registry.names:
                full = f"/{name}"
                if full.startswith(cmd):
                    desc = self._registry.get(name)
                    yield Completion(
                        full,
                        start_position=-len(cmd),
                        display_meta=desc.description if desc else "",
                    )
            for alias, target in sorted(self._registry._aliases.items()):
                full = f"/{alias}"
                if full.startswith(cmd):
                    yield Completion(
                        full,
                        start_position=-len(cmd),
                        display_meta=f"→ /{target}",
                    )
        else:
            sub_text = parts[1] if len(parts) > 1 else ""
            subs = self._SUBCOMMANDS.get(cmd, [])
            for sub in subs:
                if sub.startswith(sub_text):
                    yield Completion(
                        sub,
                        start_position=-len(sub_text),
                    )


class FileCompleter(Completer):
    """Complete file paths after ``@`` in the input buffer.

    Walks the project directory and yields relative paths that match
    the text after ``@``.  Hidden directories (starting with ``.``) and
    common noise directories (``node_modules``, ``__pycache__``, ``.git``)
    are skipped.
    """

    _SKIP_DIRS = frozenset({
        ".git", ".hg", ".svn", "node_modules", "__pycache__",
        ".venv", "venv", ".tox", ".eggs", ".mypy_cache",
        ".ruff_cache", ".pytest_cache", "dist", "build",
    })

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Find the last @ that starts a file reference
        at_idx = text.rfind("@")
        if at_idx < 0:
            return
        # @ must be at start or preceded by whitespace
        if at_idx > 0 and not text[at_idx - 1].isspace():
            return

        partial = text[at_idx + 1:]
        # Don't match if there's a space after @ (not a file ref)
        if " " in partial:
            return

        for rel in self._walk_files(partial):
            yield Completion(
                rel,
                start_position=-len(partial),
                display_meta="file",
            )

    def _walk_files(
        self, prefix: str, max_results: int = 50,
    ) -> list[str]:
        """Walk the project tree and return matching relative paths."""
        results: list[str] = []
        prefix_lower = prefix.lower()
        root = self._working_dir

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped dirs in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in self._SKIP_DIRS and not d.startswith(".")
            ]
            rel_dir = os.path.relpath(dirpath, root)
            if rel_dir == ".":
                rel_dir = ""

            for fname in filenames:
                if fname.startswith("."):
                    continue
                rel = (
                    os.path.join(rel_dir, fname) if rel_dir
                    else fname
                )
                if prefix_lower and prefix_lower not in rel.lower():
                    continue
                results.append(rel)
                if len(results) >= max_results:
                    return results

        return results
