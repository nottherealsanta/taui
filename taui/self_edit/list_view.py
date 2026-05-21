"""Text-mode listing of the self-edit inventory.

Used by `/self-edit list [category]` as a modal-less fallback that works
on any terminal size and is grep-able in transcripts.
"""

from __future__ import annotations

from pathlib import Path

from taui.self_edit import inventory


def format_inventory_listing(
    working_dir: Path, *, category: str | None = None
) -> str:
    """Render the inventory for one (or all) categories as Rich markup.

    Raises KeyError if `category` is provided but unknown — callers should
    catch this to render a friendly error message.
    """
    if category:
        cats = [inventory.category_by_key(category)]
    else:
        cats = list(inventory.CATEGORIES)

    lines: list[str] = []
    for cat in cats:
        lines.append("")
        lines.append(f"[bold #f0c808]▰ {cat.label}[/bold #f0c808]  [dim]· {cat.description}[/dim]")
        for scope in ("global", "project"):
            scope_root = inventory.scope_root(working_dir, scope)
            items = inventory.list_items(working_dir, cat.key, scope)
            lines.append(
                f"  [#c9a300]{scope}[/#c9a300]"
                f"  [dim]{scope_root}[/dim]"
            )
            if not items:
                lines.append("    [#666](none)[/#666]")
                continue
            for item in items:
                marker = "■" if item.builtin else "▸"
                builtin = " [dim](builtin)[/dim]" if item.builtin else ""
                lines.append(
                    f"    [#c9a300]{marker}[/#c9a300] "
                    f"[bold #f0c808]{item.label:<22s}[/bold #f0c808] "
                    f"{_escape(item.summary)}{builtin}"
                )
    lines.append("")
    lines.append(
        "[dim]Use /i (or /self-edit) to open the modal editor.[/dim]"
    )
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape Rich markup brackets in user-provided strings."""
    return text.replace("[", r"\[").replace("]", r"\]")
