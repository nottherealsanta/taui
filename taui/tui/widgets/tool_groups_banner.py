"""Context-banner widget: tools grouped into columns, clickable to open a modal.

The banner renders the tool groups as a fixed-column table — dark grey at
rest, brighter on hover — exactly like the SystemPromptWidget preview/modal
pair. A single click on the banner opens a modal listing every group with
its members (names only). The modal also has a button that opens the tools
page of the self-edit modal.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Static

# Same palette as the legacy table: dim by default, bright on hover.
_TOOL_DEFAULT_COLOR = "#5a5a5a"
_TOOL_HOVER_COLOR = "#bfbfbf"
_TOOL_INACTIVE_COLOR = "#3a3a3a"


class OpenToolsSelfEdit(Message):
    """Posted when the user asks to jump to the self-edit tools page."""


class ToolsModal(ModalScreen[None]):
    """Modal listing every tool group with its members (names only)."""

    DEFAULT_CSS = """
    ToolsModal {
        align: center middle;
    }
    #tools-modal-dialog {
        width: 80%;
        height: 80%;
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
        scrollbar-size-vertical: 1;
    }
    #tools-modal-dialog .tm-group {
        color: #56d4dd;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #tools-modal-dialog .tm-tool-name {
        color: #c9d1d9;
        padding: 0 0 0 2;
    }
    #tools-modal-dialog .tm-tool-name.-inactive {
        color: #6a6a6a;
    }
    #tools-modal-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    #tools-modal-dialog #tm-edit-button {
        margin: 0 1;
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
                        for name, _desc, active in members:
                            classes = (
                                "tm-tool-name"
                                if active
                                else "tm-tool-name -inactive"
                            )
                            yield Static(
                                f"· {name}",
                                classes=classes,
                                markup=False,
                            )
            with Horizontal(classes="button-container"):
                yield Button(
                    "Edit tools…",
                    variant="default",
                    id="tm-edit-button",
                )
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tm-edit-button":
            # Pop this modal, then ask the app to open self-edit on tools.
            self.app.post_message(OpenToolsSelfEdit())
            self.dismiss(None)
            return
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


def _render_columns(
    groups: dict[str, list[tuple[str, str, bool]]],
    *,
    color: str,
    columns: int = 3,
) -> str:
    """Render the group/tool list as fixed-width columns of tool names.

    Groups are emitted as labeled blocks; tools are flattened across columns
    in the legacy fashion so the banner stays compact.
    """
    if not groups:
        return ""
    lines: list[str] = []
    for group in sorted(groups):
        members = groups[group]
        names = [name for name, _, _ in members]
        if not names:
            continue
        if len(names) > 1:
            lines.append(
                f"[{color}]▾ {group}({len(names)})[/{color}]"
            )
            indent = "  "
        else:
            indent = ""
        col_width = max((len(n) for n in names), default=0) + 2
        for i in range(0, len(names), columns):
            chunk = names[i:i + columns]
            cells = []
            for j, name in enumerate(chunk):
                padded = name if j == len(chunk) - 1 else name.ljust(col_width)
                cells.append(f"[{color}]{padded}[/{color}]")
            lines.append(indent + "".join(cells))
    return "\n".join(lines)


class ToolGroupsBanner(Container):
    """Context banner showing tool groups as columns; whole banner is clickable.

    Renders dim grey at rest, brighter on hover — mirrors the visual
    treatment of the SystemPromptWidget preview.
    """

    DEFAULT_CSS = """
    ToolGroupsBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 2;
    }
    ToolGroupsBanner > Static {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        groups: dict[str, list[tuple[str, str, bool]]],
    ) -> None:
        super().__init__()
        self._groups = groups
        self._hover = False

    def compose(self) -> ComposeResult:
        yield Static(self._render(), markup=True)

    def _render(self) -> str:
        color = _TOOL_HOVER_COLOR if self._hover else _TOOL_DEFAULT_COLOR
        return _render_columns(self._groups, color=color)

    def _refresh_text(self) -> None:
        try:
            self.query_one(Static).update(self._render())
        except Exception:
            pass

    def set_groups(
        self, groups: dict[str, list[tuple[str, str, bool]]]
    ) -> None:
        """Replace the preview with a fresh group set."""
        self._groups = groups
        self._refresh_text()

    def on_enter(self, _event: events.Enter) -> None:
        self._hover = True
        self._refresh_text()

    def on_leave(self, _event: events.Leave) -> None:
        self._hover = False
        self._refresh_text()

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
