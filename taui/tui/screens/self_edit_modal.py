"""Self-edit modal — futuristic yellow construction console.

A single modal that exposes CRUD over every self-edit category (agents,
skills, commands, tools, prompts, MCP servers) across both scopes
(global, project). Used by Ctrl+E and `/self-edit`.

Visual theme: yellow construction. Black background, hazard-yellow accent
(#f0c808), stripe borders, and a `▰▰▰` futuristic glyph header. Looks like
the kind of console you'd see behind a "WORK IN PROGRESS" tape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from taui.self_edit import inventory


CONSTRUCTION_YELLOW = "#f0c808"
HAZARD_AMBER = "#ffae00"
DEEP_BLACK = "#0a0a0a"
GRID_GREY = "#3d3d3d"


@dataclass(frozen=True, slots=True)
class _ItemKey:
    category: str
    scope: str
    identifier: str


class _StripeBar(Static):
    """A one-row warning-stripe divider."""

    DEFAULT_CSS = """
    _StripeBar {
        height: 1;
        color: #0a0a0a;
        background: #f0c808;
        content-align: center middle;
        text-style: bold;
    }
    """


class _Editor(ModalScreen):
    """Sub-modal: edit body text + optional metadata fields for an item."""

    DEFAULT_CSS = f"""
    _Editor {{
        align: center middle;
        background: $background 70%;
    }}
    #se-editor-dialog {{
        width: 90%;
        height: 90%;
        background: {DEEP_BLACK};
        border: thick {CONSTRUCTION_YELLOW};
        padding: 0 1 1 1;
    }}
    #se-editor-dialog .se-editor-header {{
        height: 1;
        color: {DEEP_BLACK};
        background: {CONSTRUCTION_YELLOW};
        content-align: center middle;
        text-style: bold;
    }}
    #se-editor-dialog .se-editor-subheader {{
        height: 1;
        color: {CONSTRUCTION_YELLOW};
        padding: 0 1;
        text-style: bold;
    }}
    #se-editor-dialog .se-field-row {{
        height: 3;
        width: 100%;
        padding: 0;
    }}
    #se-editor-dialog .se-field-label {{
        width: 18;
        height: 3;
        color: {CONSTRUCTION_YELLOW};
        content-align: left middle;
        padding: 1 1 0 1;
        text-style: bold;
    }}
    #se-editor-dialog Input {{
        width: 1fr;
        height: 3;
        border: solid {GRID_GREY};
        background: {DEEP_BLACK};
        color: {CONSTRUCTION_YELLOW};
    }}
    #se-editor-dialog Input:focus {{
        border: solid {CONSTRUCTION_YELLOW};
    }}
    #se-editor-dialog TextArea {{
        height: 1fr;
        width: 100%;
        border: solid {GRID_GREY};
        background: {DEEP_BLACK};
        color: #f5f5f5;
    }}
    #se-editor-dialog TextArea:focus {{
        border: solid {CONSTRUCTION_YELLOW};
    }}
    #se-editor-dialog .se-editor-footer {{
        height: 1;
        width: 100%;
        margin: 1 0 0 0;
        align-horizontal: right;
    }}
    #se-editor-dialog .se-editor-footer Button {{
        margin: 0 0 0 1;
        height: 1;
        min-width: 0;
        border: none;
        padding: 0 1;
        background: {GRID_GREY};
        color: {CONSTRUCTION_YELLOW};
    }}
    #se-editor-dialog .se-editor-footer Button.-primary {{
        background: {CONSTRUCTION_YELLOW};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        category: inventory.Category,
        scope: str,
        creating: bool,
        item: inventory.Item | None,
        identifier: str = "",
    ) -> None:
        super().__init__()
        self._category = category
        self._scope = scope
        self._creating = creating
        self._item = item
        self._initial_id = identifier or (item.identifier if item else "")
        self._initial_body = (item.body if item else category.new_template)
        self._initial_extra = dict(item.extra) if item else {}

    def compose(self) -> ComposeResult:
        verb = "NEW" if self._creating else "EDIT"
        header = (
            f"▰▰▰  {verb} · {self._category.label} · "
            f"{self._scope.upper()} SCOPE  ▰▰▰"
        )
        with Container(id="se-editor-dialog"):
            yield Static(header, classes="se-editor-header")
            yield Static(
                "[ ESC cancel · Ctrl+S save ]",
                classes="se-editor-subheader",
            )
            yield from self._compose_fields()
            yield TextArea(self._initial_body, id="se-editor-body")
            with Horizontal(classes="se-editor-footer"):
                yield Button("Cancel", id="se-editor-cancel")
                yield Button("Save", id="se-editor-save", classes="-primary")

    def _compose_fields(self) -> ComposeResult:
        with Horizontal(classes="se-field-row"):
            yield Label("ID / NAME", classes="se-field-label")
            yield Input(
                value=self._initial_id,
                placeholder=self._id_placeholder(),
                id="se-editor-id",
                disabled=not self._creating,
            )
        if self._category.key == "agents":
            with Horizontal(classes="se-field-row"):
                yield Label("DISPLAY NAME", classes="se-field-label")
                yield Input(
                    value=str(self._initial_extra.get("name", "")),
                    id="se-editor-display",
                )
            with Horizontal(classes="se-field-row"):
                yield Label("PROVIDER", classes="se-field-label")
                yield Input(
                    value=str(self._initial_extra.get("provider", "")),
                    id="se-editor-provider",
                )
            with Horizontal(classes="se-field-row"):
                yield Label("MODEL", classes="se-field-label")
                yield Input(
                    value=str(self._initial_extra.get("model", "")),
                    id="se-editor-model",
                )
            with Horizontal(classes="se-field-row"):
                yield Label("ALLOWED TOOLS", classes="se-field-label")
                yield Input(
                    value=", ".join(self._initial_extra.get("allowed_tools", [])),
                    placeholder="comma-separated, e.g. read, edit, bash",
                    id="se-editor-tools",
                )

    def _id_placeholder(self) -> str:
        if self._category.key == "agents":
            return "3-letter UPPERCASE id (e.g. RDR)"
        if self._category.key == "skills":
            return "kebab-case skill name"
        if self._category.key == "mcp":
            return "server name (no spaces)"
        return "identifier"

    def on_mount(self) -> None:
        if self._creating:
            try:
                self.query_one("#se-editor-id", Input).focus()
            except Exception:
                pass
        else:
            try:
                self.query_one("#se-editor-body", TextArea).focus()
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._submit()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "se-editor-save":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        try:
            ident = self.query_one("#se-editor-id", Input).value.strip()
            body = self.query_one("#se-editor-body", TextArea).text
        except Exception:
            self.dismiss(None)
            return
        if not ident:
            return
        if self._category.key == "agents":
            ident = ident.upper()
        extra: dict = {}
        if self._category.key == "agents":
            try:
                extra = {
                    "name": self.query_one("#se-editor-display", Input).value.strip()
                    or ident,
                    "provider": self.query_one(
                        "#se-editor-provider", Input
                    ).value.strip(),
                    "model": self.query_one("#se-editor-model", Input).value.strip(),
                    "allowed_tools": [
                        s.strip()
                        for s in self.query_one(
                            "#se-editor-tools", Input
                        ).value.split(",")
                        if s.strip()
                    ],
                }
            except Exception:
                extra = {}
        self.dismiss(
            {
                "identifier": ident,
                "body": body,
                "extra": extra,
            }
        )


class _ConfirmDelete(ModalScreen[bool]):
    DEFAULT_CSS = f"""
    _ConfirmDelete {{
        align: center middle;
        background: $background 70%;
    }}
    #se-confirm {{
        width: 60;
        height: auto;
        background: {DEEP_BLACK};
        border: thick {HAZARD_AMBER};
        padding: 1 2;
    }}
    #se-confirm Static {{
        color: {CONSTRUCTION_YELLOW};
    }}
    #se-confirm .se-confirm-stripe {{
        height: 1;
        color: {DEEP_BLACK};
        background: {HAZARD_AMBER};
        content-align: center middle;
        text-style: bold;
        margin: 0 0 1 0;
    }}
    #se-confirm Horizontal {{
        height: 1;
        margin-top: 1;
        align-horizontal: right;
    }}
    #se-confirm Button {{
        margin: 0 0 0 1;
        border: none;
        padding: 0 1;
        height: 1;
        min-width: 0;
        background: {GRID_GREY};
        color: {CONSTRUCTION_YELLOW};
    }}
    #se-confirm Button.-danger {{
        background: {HAZARD_AMBER};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    """

    def __init__(self, *, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        with Container(id="se-confirm"):
            yield Static("⚠  DEMOLITION  ⚠", classes="se-confirm-stripe")
            yield Static(f"Delete [bold]{self._label}[/bold]?")
            yield Static("[dim]This action cannot be undone.[/dim]", markup=True)
            with Horizontal():
                yield Button("Cancel", id="se-confirm-cancel")
                yield Button("Delete", id="se-confirm-yes", classes="-danger")

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(False)
        elif event.key == "enter":
            event.stop()
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "se-confirm-yes")


class SelfEditModal(ModalScreen[str | None]):
    """Main self-edit modal: tabs + list + actions."""

    DEFAULT_CSS = f"""
    SelfEditModal {{
        align: center middle;
        background: $background 70%;
    }}
    #se-dialog {{
        width: 95%;
        height: 90%;
        background: {DEEP_BLACK};
        border: thick {CONSTRUCTION_YELLOW};
        padding: 0;
    }}
    #se-header {{
        height: 1;
        background: {CONSTRUCTION_YELLOW};
        color: {DEEP_BLACK};
        content-align: center middle;
        text-style: bold;
    }}
    #se-tabs {{
        height: 1;
        background: {DEEP_BLACK};
        color: {CONSTRUCTION_YELLOW};
        padding: 0 1;
    }}
    #se-scope-bar {{
        height: 1;
        background: {DEEP_BLACK};
        color: {CONSTRUCTION_YELLOW};
        padding: 0 1;
    }}
    #se-description {{
        height: 2;
        color: #aaaaaa;
        padding: 0 1;
    }}
    #se-body {{
        height: 1fr;
        background: {DEEP_BLACK};
        padding: 0 1;
    }}
    #se-list-pane {{
        width: 40%;
        height: 1fr;
        border-right: solid {GRID_GREY};
        padding: 0 1 0 0;
    }}
    #se-list-pane OptionList {{
        height: 1fr;
        width: 100%;
        background: {DEEP_BLACK};
        color: {CONSTRUCTION_YELLOW};
        border: solid {GRID_GREY};
    }}
    #se-list-pane OptionList:focus {{
        border: solid {CONSTRUCTION_YELLOW};
    }}
    #se-list-pane .option-list--option-highlighted {{
        background: {CONSTRUCTION_YELLOW} 20%;
        color: {CONSTRUCTION_YELLOW};
        text-style: bold;
    }}
    #se-preview-pane {{
        width: 1fr;
        height: 1fr;
        padding: 0 0 0 1;
    }}
    #se-preview-pane .se-preview-header {{
        height: 1;
        color: {CONSTRUCTION_YELLOW};
        text-style: bold;
        background: {DEEP_BLACK};
    }}
    #se-preview-pane #se-preview {{
        height: 1fr;
        width: 100%;
        background: {DEEP_BLACK};
        color: #cccccc;
        border: solid {GRID_GREY};
        padding: 1;
    }}
    #se-footer {{
        height: 1;
        background: {CONSTRUCTION_YELLOW};
        color: {DEEP_BLACK};
        content-align: center middle;
        text-style: bold;
        padding: 0 1;
    }}
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("tab", "next_scope", "Toggle scope"),
        ("right", "next_category", "Next category"),
        ("left", "prev_category", "Prev category"),
        ("n", "new_item", "New"),
        ("e", "edit_item", "Edit"),
        ("d", "delete_item", "Delete"),
        ("enter", "edit_item", "Open"),
        ("g", "set_global", "Global"),
        ("p", "set_project", "Project"),
    ]

    def __init__(
        self,
        working_dir: Path,
        *,
        initial_scope: str = "global",
        initial_category: str = "agents",
    ) -> None:
        super().__init__()
        self._working_dir = working_dir
        self._scope = initial_scope
        self._category_index = max(
            0,
            next(
                (
                    i
                    for i, c in enumerate(inventory.CATEGORIES)
                    if c.key == initial_category
                ),
                0,
            ),
        )
        self._items: list[inventory.Item] = []

    @property
    def _category(self) -> inventory.Category:
        return inventory.CATEGORIES[self._category_index]

    def compose(self) -> ComposeResult:
        with Container(id="se-dialog"):
            yield Static(self._render_header(), id="se-header", markup=True)
            yield Static(self._render_tabs(), id="se-tabs", markup=True)
            yield Static(self._render_scope(), id="se-scope-bar", markup=True)
            yield Static(self._category.description, id="se-description")
            with Horizontal(id="se-body"):
                with Vertical(id="se-list-pane"):
                    yield OptionList(id="se-options")
                with Vertical(id="se-preview-pane"):
                    yield Static(
                        "[bold]PREVIEW[/bold]",
                        classes="se-preview-header",
                        markup=True,
                    )
                    yield Static("", id="se-preview", markup=False)
            yield Static(self._render_footer(), id="se-footer", markup=True)

    def on_mount(self) -> None:
        self._refresh_items()
        try:
            self.query_one("#se-options", OptionList).focus()
        except Exception:
            pass

    # ── Rendering ─────────────────────────────────────────────────

    def _render_header(self) -> str:
        return (
            "▰▰▰  S E L F · E D I T   C O N S O L E   "
            "·   U N D E R   C O N S T R U C T I O N  ▰▰▰"
        )

    def _render_tabs(self) -> str:
        parts: list[str] = []
        c = inventory.counts(self._working_dir)
        for i, cat in enumerate(inventory.CATEGORIES):
            count = c.get(cat.key, {}).get(self._scope, 0)
            label = f"{cat.label} ({count})"
            if i == self._category_index:
                parts.append(
                    f"[black on #f0c808] ▸ {label} [/black on #f0c808]"
                )
            else:
                parts.append(f"[#f0c808]  {label}  [/#f0c808]")
        return "".join(parts)

    def _render_scope(self) -> str:
        scope_root = inventory.scope_root(self._working_dir, self._scope)
        active = self._scope.upper()
        inactive_label = "PROJECT" if self._scope == "global" else "GLOBAL"
        return (
            f"[#0a0a0a on #f0c808] SCOPE: {active} [/#0a0a0a on #f0c808] "
            f"[#f0c808]{scope_root}[/#f0c808]  "
            f"[dim]· Tab → {inactive_label}[/dim]"
        )

    def _render_footer(self) -> str:
        return (
            "[ n NEW · e EDIT · d DELETE · ←→ CATEGORY · Tab SCOPE · Esc CLOSE ]"
        )

    def _refresh_items(self) -> None:
        self._items = inventory.list_items(
            self._working_dir, self._category.key, self._scope
        )
        try:
            opts = self.query_one("#se-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        if not self._items:
            opts.add_option(
                Option(
                    Text("(empty — press 'n' to create one)", style=f"italic {GRID_GREY}"),
                    id="__empty__",
                    disabled=True,
                )
            )
        else:
            for item in self._items:
                opts.add_option(
                    Option(self._render_item_row(item), id=item.identifier)
                )
            opts.highlighted = 0
        self._update_preview()
        # refresh dynamic header/tabs/scope/description
        try:
            self.query_one("#se-tabs", Static).update(self._render_tabs())
            self.query_one("#se-scope-bar", Static).update(self._render_scope())
            self.query_one("#se-description", Static).update(
                self._category.description
            )
        except Exception:
            pass

    def _render_item_row(self, item: inventory.Item) -> Text:
        text = Text()
        marker = "■" if item.builtin else "▸"
        text.append(f" {marker} ", style=CONSTRUCTION_YELLOW)
        text.append(f"{item.label:<24s}", style=f"bold {CONSTRUCTION_YELLOW}")
        suffix = " [builtin]" if item.builtin else ""
        text.append(f" {item.summary}{suffix}", style="white")
        return text

    def _current_item(self) -> inventory.Item | None:
        try:
            opts = self.query_one("#se-options", OptionList)
        except Exception:
            return None
        idx = opts.highlighted
        if idx is None or idx < 0 or idx >= len(self._items):
            return None
        return self._items[idx]

    def _update_preview(self) -> None:
        try:
            preview = self.query_one("#se-preview", Static)
        except Exception:
            return
        item = self._current_item()
        if item is None:
            preview.update("(no item selected)")
            return
        excerpt = item.body
        if len(excerpt) > 4000:
            excerpt = excerpt[:4000] + "\n… (truncated)"
        header = f"{item.path}"
        preview.update(f"{header}\n{'─' * min(60, len(header))}\n{excerpt}")

    # ── Actions ───────────────────────────────────────────────────

    @on(OptionList.OptionHighlighted)
    def _on_option_highlighted(self, _: OptionList.OptionHighlighted) -> None:
        self._update_preview()

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id == "__empty__":
            self.action_new_item()
            return
        self.action_edit_item()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_next_scope(self) -> None:
        self._scope = "project" if self._scope == "global" else "global"
        self._refresh_items()

    def action_set_global(self) -> None:
        self._scope = "global"
        self._refresh_items()

    def action_set_project(self) -> None:
        self._scope = "project"
        self._refresh_items()

    def action_next_category(self) -> None:
        self._category_index = (self._category_index + 1) % len(inventory.CATEGORIES)
        self._refresh_items()

    def action_prev_category(self) -> None:
        self._category_index = (
            self._category_index - 1
        ) % len(inventory.CATEGORIES)
        self._refresh_items()

    def action_new_item(self) -> None:
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=True,
            item=None,
        )

        def after(result):
            if result is None:
                return
            try:
                inventory.save_item(
                    self._working_dir,
                    self._category.key,
                    self._scope,
                    result["identifier"],
                    result["body"],
                    result.get("extra"),
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.app.bell()
                self._toast(f"Save failed: {exc}")
                return
            self._refresh_items()

        self.app.push_screen(editor, after)

    def action_edit_item(self) -> None:
        item = self._current_item()
        if item is None:
            self.action_new_item()
            return
        if item.builtin:
            # Allow editing the prompt body of built-ins (they migrate to user
            # scope on save), but disable identifier changes.
            pass
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=False,
            item=item,
        )

        def after(result):
            if result is None:
                return
            try:
                inventory.save_item(
                    self._working_dir,
                    self._category.key,
                    self._scope,
                    result["identifier"] or item.identifier,
                    result["body"],
                    result.get("extra"),
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.app.bell()
                self._toast(f"Save failed: {exc}")
                return
            self._refresh_items()

        self.app.push_screen(editor, after)

    def action_delete_item(self) -> None:
        item = self._current_item()
        if item is None:
            return
        if item.builtin:
            self._toast("Built-in items cannot be deleted.")
            return

        confirm = _ConfirmDelete(label=f"{self._category.label} · {item.label}")

        def after(confirmed):
            if not confirmed:
                return
            try:
                inventory.delete_item(
                    self._working_dir,
                    self._category.key,
                    self._scope,
                    item.identifier,
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.app.bell()
                self._toast(f"Delete failed: {exc}")
                return
            self._refresh_items()

        self.app.push_screen(confirm, after)

    def _toast(self, message: str) -> None:
        try:
            self.query_one("#se-description", Static).update(
                f"[bold #ffae00]{message}[/bold #ffae00]"
            )
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        # Only handle escape here so OptionList's own enter/arrow keys still
        # work when it has focus.
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
