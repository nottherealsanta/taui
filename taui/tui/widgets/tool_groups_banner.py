"""Context-banner widget: shows tool groups as clickable pills.

Each pill renders ``<group>(<count>)``. Clicking a pill opens a modal
listing the tools in that group with their descriptions — same UX as
the SystemPromptWidget preview/modal pair.
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


class ToolGroupModal(ModalScreen[None]):
    """Modal showing the tools that belong to a single group."""

    DEFAULT_CSS = """
    ToolGroupModal {
        align: center middle;
    }
    #tool-group-dialog {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #tool-group-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #tool-group-dialog #tg-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #tool-group-dialog .tg-tool-name {
        color: #d2a8ff;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #tool-group-dialog .tg-tool-desc {
        color: #c9d1d9;
        padding: 0 0 0 2;
    }
    #tool-group-dialog .tg-tool-state {
        color: #888;
        padding: 0 0 0 2;
    }
    #tool-group-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(
        self,
        group: str,
        members: list[tuple[str, str, bool]],
    ) -> None:
        """``members`` is a list of (tool_name, description, active)."""
        super().__init__()
        self._group = group
        self._members = members

    def compose(self) -> ComposeResult:
        with Container(id="tool-group-dialog"):
            yield Static(
                f"[bold]Tool group: {self._group}  "
                f"({len(self._members)} tool"
                f"{'s' if len(self._members) != 1 else ''})[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="tg-scroll"):
                if not self._members:
                    yield Static(
                        "(empty — no tools in this group)", markup=False
                    )
                else:
                    for name, desc, active in self._members:
                        state = "active" if active else "inactive"
                        color = (
                            _TOOL_ACTIVE_COLOR if active else _TOOL_INACTIVE_COLOR
                        )
                        yield Static(
                            f"[bold {color}]{name}[/]  [dim]({state})[/dim]",
                            classes="tg-tool-name",
                            markup=True,
                        )
                        yield Static(
                            desc or "(no description)",
                            classes="tg-tool-desc",
                            markup=False,
                        )
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class _ToolGroupPill(Static):
    """One clickable ``<group>(<count>)`` pill."""

    DEFAULT_CSS = """
    _ToolGroupPill {
        width: auto;
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        color: #bfbfbf;
    }
    _ToolGroupPill.-inactive {
        color: #5a5a5a;
    }
    _ToolGroupPill:hover {
        background: $surface-lighten-1 20%;
        color: #ffffff;
    }
    """

    def __init__(
        self,
        group: str,
        members: list[tuple[str, str, bool]],
    ) -> None:
        super().__init__()
        self._group = group
        self._members = members
        if not any(active for _, _, active in members):
            self.add_class("-inactive")

    def render(self) -> str:
        return f"{self._group}({len(self._members)})"

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(
            ToolGroupModal(self._group, self._members)
        )


class ToolGroupsBanner(Container):
    """Context banner showing tool groups as clickable pills."""

    DEFAULT_CSS = """
    ToolGroupsBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 2;
    }
    ToolGroupsBanner > Horizontal {
        width: 100%;
        height: auto;
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
        with Horizontal():
            for group in sorted(self._groups):
                yield _ToolGroupPill(group, self._groups[group])

    def set_groups(
        self, groups: dict[str, list[tuple[str, str, bool]]]
    ) -> None:
        """Replace the pills with a fresh group set."""
        self._groups = groups
        try:
            row = self.query_one(Horizontal)
        except Exception:
            return
        row.remove_children()
        for group in sorted(self._groups):
            row.mount(_ToolGroupPill(group, self._groups[group]))


def build_group_payload(
    registry: Any,
    *,
    available_names: list[str],
    active_names: set[str],
) -> dict[str, list[tuple[str, str, bool]]]:
    """Resolve the (group -> [(name, desc, active)]) payload for the banner.

    Tools not present in ``registry`` (e.g. extension tools whose schema was
    captured at session start but were later unregistered) still appear as
    their own single-member group with an empty description.
    """
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
