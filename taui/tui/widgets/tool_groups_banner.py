"""Context-banner widget: shows the tool list grouped, with a click-to-open modal.

The banner renders one preview line per group (``<group>(<count>)``). The
whole banner is clickable — a single click opens a modal that lists every
group with its tools and descriptions, same UX as the SystemPromptWidget.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

# Color tokens — keep in sync with app.py
_TOOL_ACTIVE_COLOR = "#bfbfbf"
_TOOL_INACTIVE_COLOR = "#5a5a5a"


class ToolsModal(ModalScreen[None]):
    """Modal listing every tool group with its members + descriptions."""

    DEFAULT_CSS = """
    ToolsModal {
        align: center middle;
    }
    #tools-modal-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #tools-modal-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #tools-modal-dialog #tm-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #tools-modal-dialog .tm-group {
        color: #56d4dd;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #tools-modal-dialog .tm-tool-name {
        color: #d2a8ff;
        text-style: bold;
        padding: 0 0 0 2;
    }
    #tools-modal-dialog .tm-tool-desc {
        color: #c9d1d9;
        padding: 0 0 0 4;
    }
    #tools-modal-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(
        self, groups: dict[str, list[tuple[str, str, bool]]]
    ) -> None:
        super().__init__()
        self._groups = groups

    def compose(self) -> ComposeResult:
        total_tools = sum(len(m) for m in self._groups.values())
        with Container(id="tools-modal-dialog"):
            yield Static(
                f"[bold]Tools  ·  {len(self._groups)} group"
                f"{'s' if len(self._groups) != 1 else ''}"
                f"  ·  {total_tools} tool"
                f"{'s' if total_tools != 1 else ''}[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="tm-scroll"):
                if not self._groups:
                    yield Static("(no tools)", markup=False)
                else:
                    for group in sorted(self._groups):
                        members = self._groups[group]
                        yield Static(
                            f"▾ {group}  ({len(members)})",
                            classes="tm-group",
                            markup=False,
                        )
                        for name, desc, active in members:
                            state = (
                                "active" if active else "inactive"
                            )
                            color = (
                                _TOOL_ACTIVE_COLOR
                                if active
                                else _TOOL_INACTIVE_COLOR
                            )
                            yield Static(
                                f"[bold {color}]{name}[/]  "
                                f"[dim]({state})[/dim]",
                                classes="tm-tool-name",
                                markup=True,
                            )
                            yield Static(
                                desc or "(no description)",
                                classes="tm-tool-desc",
                                markup=False,
                            )
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


def _build_preview(
    groups: dict[str, list[tuple[str, str, bool]]],
) -> str:
    """Render group pills as a single static preview line."""
    if not groups:
        return ""
    parts: list[str] = []
    for group in sorted(groups):
        members = groups[group]
        any_active = any(active for _, _, active in members)
        color = _TOOL_ACTIVE_COLOR if any_active else _TOOL_INACTIVE_COLOR
        parts.append(f"[{color}]{group}({len(members)})[/{color}]")
    return "  ".join(parts)


class ToolGroupsBanner(Container):
    """Context banner showing all tool groups; whole banner is one click target."""

    DEFAULT_CSS = """
    ToolGroupsBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 2;
        color: #a0a0a0;
    }
    ToolGroupsBanner:hover {
        color: #d0d0d0;
        background: $surface-lighten-1 10%;
    }
    """

    def __init__(
        self,
        groups: dict[str, list[tuple[str, str, bool]]],
    ) -> None:
        """``groups`` maps group name -> list of (tool_name, description, active)."""
        super().__init__()
        self._groups = groups

    def compose(self) -> ComposeResult:
        yield Static(_build_preview(self._groups), markup=True)

    def set_groups(
        self, groups: dict[str, list[tuple[str, str, bool]]]
    ) -> None:
        """Replace the preview with a fresh group set."""
        self._groups = groups
        try:
            preview = self.query_one(Static)
        except Exception:
            return
        preview.update(_build_preview(self._groups))

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        if not self._groups:
            return
        await self.app.push_screen(ToolsModal(self._groups))


def build_group_payload(
    registry: Any,
    *,
    available_names: list[str],
    active_names: set[str],
) -> dict[str, list[tuple[str, str, bool]]]:
    """Resolve the (group -> [(name, desc, active)]) payload for the banner."""
    from taui.tools.base import tool_group

    out: dict[str, list[tuple[str, str, bool]]] = {}
    for name in available_names:
        active = name in active_names
        try:
            tool = registry.get(name)
            group = tool_group(tool)
            desc = str(getattr(tool, "description", "") or "")
        except Exception:
            group = name
            desc = ""
        out.setdefault(group, []).append((name, desc, active))
    for members in out.values():
        members.sort(key=lambda m: m[0])
    return out
