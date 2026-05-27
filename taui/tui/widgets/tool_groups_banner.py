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

# Match the SystemPromptWidget palette so the two banners feel consistent.
_TOOL_DEFAULT_COLOR = "#a0a0a0"
_DEFAULT_LABEL_STYLE = "bold #ffffff on #8a8a8a"


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
        color: #ff9e64;
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
    #tools-modal-dialog .tm-tool-name.-solo {
        padding: 1 0 0 0;
        color: #d2a8ff;
        text-style: bold;
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
                        # Multi-tool groups get a header; solo tools are
                        # listed flat as their own name.
                        if len(members) > 1:
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
                        else:
                            name, _desc, active = members[0]
                            classes = (
                                "tm-tool-name -solo"
                                if active
                                else "tm-tool-name -solo -inactive"
                            )
                            yield Static(
                                name, classes=classes, markup=False
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


def _format_group_label(group: str, count: int) -> str:
    """``bash(3)`` for multi-tool groups, ``read`` for solo groups."""
    return f"{group}({count})" if count > 1 else group


def _render_columns(
    groups: dict[str, list[tuple[str, str, bool]]],
    *,
    color: str,
    columns: int = 3,
) -> str:
    """Render the group list as fixed-width columns of group labels.

    Each cell is ``<group>(<count>)`` (count omitted when 1). One cell per
    group — individual tool names live behind the click-to-open modal.
    """
    if not groups:
        return ""
    labels = [
        _format_group_label(g, len(groups[g]))
        for g in sorted(groups)
        if groups[g]
    ]
    if not labels:
        return ""
    col_width = max((len(label) for label in labels), default=0) + 2
    rows: list[str] = []
    for i in range(0, len(labels), columns):
        chunk = labels[i:i + columns]
        cells = []
        for j, label in enumerate(chunk):
            padded = (
                label if j == len(chunk) - 1 else label.ljust(col_width)
            )
            cells.append(f"[{color}]{padded}[/{color}]")
        rows.append("".join(cells))
    return "\n".join(rows)


class ToolGroupsBanner(Container):
    """Context banner: header label + tool group grid, all in one widget.

    The entire widget is clickable — header or body — and the whole
    container highlights on hover. Clicking opens the tools modal.
    """

    DEFAULT_CSS = """
    ToolGroupsBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 1;
        color: #a0a0a0;
    }
    ToolGroupsBanner:hover {
        background: #2a2a2a;
        color: #e8e8e8;
    }
    ToolGroupsBanner .banner-label {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0 1 0 0;
    }
    ToolGroupsBanner .banner-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
        margin: 0 1 1 1;
    }
    """

    def __init__(
        self,
        groups: dict[str, list[tuple[str, str, bool]]],
        *,
        label_text: str = "Tools",
        label_style: str = _DEFAULT_LABEL_STYLE,
    ) -> None:
        super().__init__()
        self._groups = groups
        self._label_text = label_text
        self._label_style = label_style

    def compose(self) -> ComposeResult:
        yield Static(
            self._render_label(),
            classes="banner-label",
            markup=True,
        )
        yield Static(
            self._render_body(),
            classes="banner-body",
            markup=True,
        )

    def _render_label(self) -> str:
        return f"[{self._label_style}] {self._label_text} [/]"

    def _render_body(self) -> str:
        return _render_columns(self._groups, color=_TOOL_DEFAULT_COLOR)

    def set_groups(
        self,
        groups: dict[str, list[tuple[str, str, bool]]],
        *,
        label_style: str | None = None,
    ) -> None:
        """Replace the preview with a fresh group set."""
        self._groups = groups
        if label_style is not None:
            self._label_style = label_style
        try:
            self.query_one(".banner-body", Static).update(self._render_body())
            self.query_one(".banner-label", Static).update(self._render_label())
        except Exception:
            pass

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
