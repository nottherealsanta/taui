"""Self-edit modal — futuristic yellow console.

A single modal that exposes CRUD over every self-edit category (agents,
skills, commands, tools, prompts, MCP servers) across both scopes
(global, project). Used by Ctrl+E and `/self-edit`.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Click, Key
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

# ── Palette ──────────────────────────────────────────────────────────
ACCENT = "#f0c808"        # bright hazard yellow — highlights / active state
ACCENT_SOFT = "#c9a300"   # warm yellow — body text accents
BORDER = "#5a4500"        # dark olive — subtle yellow border
PANEL_BG = "#0d0d0d"      # dialog background
INNER_BG = "#121212"      # slightly lighter for sub-panels
DEEP_BLACK = "#0a0a0a"
HAZARD_AMBER = "#ffae00"  # warning/destructive accent
GRID_GREY = "#2a2a2a"     # darker grey for inner borders


# ── Custom events ───────────────────────────────────────────────────


class _CategoryClicked(events.Event):
    def __init__(self, category_key: str) -> None:
        super().__init__()
        self.category_key = category_key


class _ScopeClicked(events.Event):
    def __init__(self, scope: str) -> None:
        super().__init__()
        self.scope = scope


# ── Clickable chrome widgets ────────────────────────────────────────


class _CategoryTab(Static):
    """Single clickable category tab inside the modal header."""

    DEFAULT_CSS = f"""
    _CategoryTab {{
        height: 1;
        width: auto;
        padding: 0 2;
        color: {ACCENT_SOFT};
        background: {PANEL_BG};
        content-align: center middle;
    }}
    _CategoryTab.-active {{
        color: {DEEP_BLACK};
        background: {ACCENT};
        text-style: bold;
    }}
    _CategoryTab:hover {{
        color: {ACCENT};
        text-style: bold;
    }}
    _CategoryTab.-active:hover {{
        color: {DEEP_BLACK};
    }}
    """

    def __init__(self, key: str, label: str, count: int, *, active: bool) -> None:
        super().__init__()
        self._key = key
        self._label = label
        self._count = count
        if active:
            self.add_class("-active")

    def render(self) -> str:
        if self._key == "general":
            return self._label
        return f"{self._label} {self._count}"

    @property
    def category_key(self) -> str:
        return self._key

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(_CategoryClicked(self._key))


class _ScopeChip(Static):
    """Clickable scope chip — global / project."""

    DEFAULT_CSS = f"""
    _ScopeChip {{
        height: 1;
        width: auto;
        padding: 0 2;
        color: {ACCENT_SOFT};
        background: {PANEL_BG};
        content-align: center middle;
    }}
    _ScopeChip.-active {{
        color: {DEEP_BLACK};
        background: {ACCENT};
        text-style: bold;
    }}
    _ScopeChip:hover {{
        color: {ACCENT};
        text-style: bold;
    }}
    _ScopeChip.-active:hover {{
        color: {DEEP_BLACK};
    }}
    """

    def __init__(self, scope: str, *, active: bool) -> None:
        super().__init__()
        self._scope = scope
        if active:
            self.add_class("-active")

    def render(self) -> str:
        return self._scope.upper()

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(_ScopeClicked(self._scope))


# ── Tool toggle (one cell in the allowed-tools grid) ────────────────


class _ToolToggle(Static):
    """Single clickable tool name with on/off state.

    Carries an optional ``group`` so a parent _ToolGroupToggle can find its
    members and so the parent editor can keep the group header in sync.
    """

    class Changed(events.Event):
        def __init__(self, tool_name: str, group: str, selected: bool) -> None:
            super().__init__()
            self.tool_name = tool_name
            self.group = group
            self.selected = selected

    DEFAULT_CSS = f"""
    _ToolToggle {{
        height: 1;
        width: 1fr;
        padding: 0 1 0 3;
        color: #555;
    }}
    _ToolToggle.-on {{
        color: {ACCENT};
        text-style: bold;
    }}
    _ToolToggle:hover {{
        background: {INNER_BG};
    }}
    """

    def __init__(
        self, tool_name: str, selected: bool, *, group: str = ""
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._selected = selected
        self._group = group or tool_name
        if selected:
            self.add_class("-on")

    def render(self) -> str:
        marker = "✓" if self._selected else "·"
        return f" {marker}  {self._tool_name}"

    def on_click(self, event: Click) -> None:
        event.stop()
        self.toggle()

    def toggle(self) -> None:
        self._selected = not self._selected
        if self._selected:
            self.add_class("-on")
        else:
            self.remove_class("-on")
        self.refresh()
        self.post_message(
            _ToolToggle.Changed(self._tool_name, self._group, self._selected)
        )

    def set_selected(self, value: bool, *, post: bool = False) -> None:
        """Programmatically set the toggle without click. Optionally post Changed."""
        if self._selected == value:
            return
        self._selected = value
        if self._selected:
            self.add_class("-on")
        else:
            self.remove_class("-on")
        self.refresh()
        if post:
            self.post_message(
                _ToolToggle.Changed(self._tool_name, self._group, value)
            )

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def group(self) -> str:
        return self._group

    @property
    def is_selected(self) -> bool:
        return self._selected


class _ToolGroupToggle(Static):
    """Group header — toggles all member tools in one click.

    The header shows ``<group>  (selected/total)``. Clicking selects all
    member tools if any are off, otherwise deselects them all. The widget
    is purely a notifier; the parent editor listens for the Changed event
    and walks the matching _ToolToggle children.
    """

    class Changed(events.Event):
        def __init__(self, group: str, select_all: bool) -> None:
            super().__init__()
            self.group = group
            self.select_all = select_all

    DEFAULT_CSS = f"""
    _ToolGroupToggle {{
        height: 1;
        width: 1fr;
        padding: 0 1;
        margin: 1 0 0 0;
        color: #888;
        text-style: bold;
    }}
    _ToolGroupToggle.-all {{
        color: {ACCENT};
    }}
    _ToolGroupToggle.-some {{
        color: {ACCENT_SOFT};
    }}
    _ToolGroupToggle:hover {{
        background: {INNER_BG};
    }}
    """

    def __init__(self, group: str, *, selected: int, total: int) -> None:
        super().__init__()
        self._group = group
        self._selected = selected
        self._total = total
        self._apply_state_class()

    def render(self) -> str:
        if self._total == 1:
            # Solo group — keep header but show no fractional count
            return f"▸ {self._group}"
        marker = (
            "▾" if self._selected == self._total
            else ("▿" if self._selected > 0 else "▹")
        )
        return f"{marker} {self._group}  ({self._selected}/{self._total})"

    def _apply_state_class(self) -> None:
        self.remove_class("-all")
        self.remove_class("-some")
        if self._selected == self._total and self._total > 0:
            self.add_class("-all")
        elif self._selected > 0:
            self.add_class("-some")

    def set_counts(self, *, selected: int, total: int) -> None:
        self._selected = selected
        self._total = total
        self._apply_state_class()
        self.refresh()

    def on_click(self, event: Click) -> None:
        event.stop()
        # If everything is on, toggle them all off; otherwise turn them all on.
        select_all = self._selected < self._total
        self.post_message(_ToolGroupToggle.Changed(self._group, select_all))

    @property
    def group(self) -> str:
        return self._group


class _ShowBuiltinToggle(Static):
    """Single clickable on/off pill for the 'show built-in' tools filter."""

    class Changed(events.Event):
        def __init__(self, value: bool) -> None:
            super().__init__()
            self.value = value

    def __init__(self, *, selected: bool) -> None:
        super().__init__(classes="se-tools-toggle")
        self._selected = selected
        if selected:
            self.add_class("-on")

    def render(self) -> str:
        marker = "✓" if self._selected else "·"
        return f" {marker} show built-in "

    def on_click(self, event: Click) -> None:
        event.stop()
        self._selected = not self._selected
        if self._selected:
            self.add_class("-on")
        else:
            self.remove_class("-on")
        self.refresh()
        self.post_message(_ShowBuiltinToggle.Changed(self._selected))


class _ListBuiltinToggle(Static):
    """Show/hide built-in items in the main category list (TOOLS tab)."""

    class Changed(events.Event):
        def __init__(self, value: bool) -> None:
            super().__init__()
            self.value = value

    def __init__(self, *, selected: bool) -> None:
        super().__init__()
        self._selected = selected
        if selected:
            self.add_class("-on")

    def render(self) -> str:
        marker = "✓" if self._selected else "·"
        return f" {marker} show built-in "

    def on_click(self, event: Click) -> None:
        event.stop()
        self._selected = not self._selected
        if self._selected:
            self.add_class("-on")
        else:
            self.remove_class("-on")
        self.refresh()
        self.post_message(_ListBuiltinToggle.Changed(self._selected))


# ── Usage toggle (main / sub / both) ───────────────────────────────


_USAGE_LABELS: dict[str, str] = {
    "main": "MAIN ONLY",
    "sub": "SUB ONLY",
    "both": "BOTH",
}


class _UsageToggle(Static):
    """Single segment of the 3-way usage selector."""

    DEFAULT_CSS = f"""
    _UsageToggle {{
        height: 1;
        width: auto;
        padding: 0 2;
        color: #666;
        background: {INNER_BG};
        content-align: center middle;
    }}
    _UsageToggle.-on {{
        color: {DEEP_BLACK};
        background: {ACCENT};
        text-style: bold;
    }}
    _UsageToggle:hover {{
        color: {ACCENT};
    }}
    _UsageToggle.-on:hover {{
        color: {DEEP_BLACK};
    }}
    """

    class Changed(events.Event):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, value: str, *, selected: bool) -> None:
        super().__init__()
        self._value = value
        if selected:
            self.add_class("-on")

    def render(self) -> str:
        return _USAGE_LABELS.get(self._value, self._value.upper())

    def on_click(self, event: Click) -> None:
        event.stop()
        if "-on" in self.classes:
            return
        self.post_message(_UsageToggle.Changed(self._value))

    @property
    def value(self) -> str:
        return self._value

    def set_active(self, active: bool) -> None:
        if active:
            self.add_class("-on")
        else:
            self.remove_class("-on")
        self.refresh()


# ── Color swatch (single colour cell) ──────────────────────────────

# Curated palette — kept short so it stays a one-row selector.
# Empty string means "no accent colour".
AGENT_COLOR_PALETTE: tuple[tuple[str, str], ...] = (
    ("",        "—"),         # no accent
    ("#f0c808", "yellow"),
    ("#7aa2f7", "blue"),
    ("#9ece6a", "green"),
    ("#bb9af7", "purple"),
    ("#f7768e", "red"),
    ("#73daca", "teal"),
    ("#ff9e64", "orange"),
    ("#e0af68", "amber"),
    ("#a9b1d6", "grey"),
)


class _ColorSwatch(Static):
    """Single clickable color cell in the agent color selector."""

    DEFAULT_CSS = f"""
    _ColorSwatch {{
        height: 1;
        width: 3;
        margin: 0 1 0 0;
        background: {INNER_BG};
        color: {INNER_BG};
        content-align: center middle;
    }}
    _ColorSwatch.-on {{
        color: #111;
        text-style: bold;
    }}
    _ColorSwatch.-none {{
        color: #555;
        background: {INNER_BG};
    }}
    _ColorSwatch.-none.-on {{
        color: {ACCENT};
    }}
    _ColorSwatch:hover {{
        text-style: bold;
    }}
    """

    class Changed(events.Event):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, color: str, *, selected: bool) -> None:
        super().__init__()
        self._color = color
        if not color:
            self.add_class("-none")
        else:
            # Per-instance background override.
            self.styles.background = color
            # When selected, use a dark contrasting text color so the
            # checkmark is visible against the colored background.
            self.styles.color = "#111" if selected else color
        if selected:
            self.add_class("-on")

    def render(self) -> str:
        if not self._color:
            return " — "
        # Render a check on selected swatches; padded with spaces so the
        # tile shows the background colour either way.
        return " ✓ " if "-on" in self.classes else "   "

    def on_click(self, event: Click) -> None:
        event.stop()
        if "-on" in self.classes:
            return
        self.post_message(_ColorSwatch.Changed(self._color))

    @property
    def value(self) -> str:
        return self._color

    def set_active(self, active: bool) -> None:
        if active:
            self.add_class("-on")
            if self._color:
                self.styles.color = "#111"
        else:
            self.remove_class("-on")
            if self._color:
                self.styles.color = self._color
        self.refresh()


# ── Fuzzy model picker (used after clicking Generate) ──────────────


class _ModelPicker(ModalScreen[str | None]):
    """Fuzzy-searchable picker for selecting which model generates."""

    DEFAULT_CSS = f"""
    _ModelPicker {{
        align: center middle;
        background: $background 70%;
    }}
    #se-mp-dialog {{
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 50%;
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 0 1 1 1;
    }}
    #se-mp-dialog .se-mp-header {{
        height: 1;
        color: {ACCENT};
        text-style: bold;
        padding: 0 1;
    }}
    #se-mp-dialog #se-mp-search {{
        height: 3;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: {ACCENT};
        margin: 0;
    }}
    #se-mp-dialog #se-mp-search:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-mp-dialog OptionList {{
        height: 12;
        width: 100%;
        background: {INNER_BG};
        color: {ACCENT_SOFT};
        border: solid {GRID_GREY};
    }}
    #se-mp-dialog OptionList:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-mp-dialog .option-list--option-highlighted {{
        background: {ACCENT} 20%;
        color: {ACCENT};
        text-style: bold;
    }}
    #se-mp-dialog .se-mp-hint {{
        height: 1;
        color: #666;
        padding: 1 1 0 1;
    }}
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        models: list[str],
        default: str = "",
        provider_of: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._models = models
        self._default = default
        self._provider_of = provider_of or {}

    def compose(self) -> ComposeResult:
        with Container(id="se-mp-dialog"):
            yield Static("◆ select model", classes="se-mp-header")
            yield Input(
                placeholder="",
                id="se-mp-search",
                value=self._default,
            )
            initial = (
                self._filter(self._default) if self._default else self._models
            )
            yield OptionList(
                *[Option(self._row(m), id=m) for m in initial],
                id="se-mp-list",
            )
            yield Static(
                "[dim]↑↓ navigate · Enter select · Esc cancel[/dim]",
                classes="se-mp-hint",
                markup=True,
            )

    def _row(self, model_id: str) -> Text:
        """Render one model row: id on the left, provider in dim grey on the right."""
        provider = self._provider_of.get(model_id, "")
        text = Text()
        # Compute padding so the provider sits flush right within the option row.
        # OptionList option width — we don't know exactly, but ~48 cols works
        # with the picker's fixed 60-col dialog (minus borders/padding).
        width = 50
        left = model_id
        right = provider
        pad = max(1, width - len(left) - len(right))
        text.append(left, style=ACCENT_SOFT)
        text.append(" " * pad)
        text.append(right, style="#777777")
        return text

    def on_mount(self) -> None:
        try:
            self.query_one("#se-mp-search", Input).focus()
        except Exception:
            pass

    def _filter(self, query: str) -> list[str]:
        q = query.lower().strip()
        if not q:
            return list(self._models)
        # Substring match first, then subsequence fuzzy match.
        substring = [m for m in self._models if q in m.lower()]
        seen = set(substring)
        subseq = [
            m for m in self._models
            if m not in seen and _subseq_match(q, m.lower())
        ]
        return substring + subseq

    @on(Input.Changed, "#se-mp-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#se-mp-list", OptionList)
        except Exception:
            return
        opts.clear_options()
        for m in self._filter(event.value):
            opts.add_option(Option(self._row(m), id=m))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#se-mp-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#se-mp-list", OptionList)
        except Exception:
            return
        if opts.option_count == 0:
            return
        idx = opts.highlighted or 0
        opt = opts.get_option_at_index(idx)
        self.dismiss(opt.id)

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
        elif event.key == "down":
            try:
                if self.focused is self.query_one("#se-mp-search", Input):
                    event.stop()
                    self.query_one("#se-mp-list", OptionList).focus()
            except Exception:
                pass


def _subseq_match(query: str, target: str) -> bool:
    """Return True if every char in `query` appears in `target` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)


# ── Editor sub-modal ────────────────────────────────────────────────


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
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 1 1 1 1;
    }}
    #se-editor-dialog .se-editor-header {{
        height: 1;
        color: {ACCENT};
        background: {PANEL_BG};
        text-style: bold;
        padding: 0 1;
    }}
    #se-editor-dialog .se-editor-subheader {{
        height: 1;
        color: {ACCENT_SOFT};
        padding: 0 1;
    }}
    #se-editor-dialog .se-field-row {{
        height: 3;
        width: 100%;
        padding: 0;
    }}
    #se-editor-dialog .se-field-label {{
        width: 18;
        height: 3;
        color: {ACCENT_SOFT};
        content-align: left middle;
        padding: 1 1 0 1;
    }}
    #se-editor-dialog Input {{
        width: 1fr;
        height: 3;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: {ACCENT};
    }}
    #se-editor-dialog Input:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-editor-dialog .se-prompt-row {{
        height: 1;
        width: 100%;
        padding: 0;
        margin-top: 1;
    }}
    #se-editor-dialog #se-editor-llm-prompt {{
        height: 1;
        border: none;
        padding: 0 1;
        background: {INNER_BG};
        width: 1fr;
    }}
    #se-editor-dialog #se-editor-llm-prompt:focus {{
        background: {INNER_BG};
        border: none;
    }}
    #se-editor-dialog #se-editor-generate {{
        margin: 0 0 0 1;
        height: 1;
        min-width: 0;
        border: none;
        padding: 0 2;
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    #se-editor-dialog #se-editor-generate.-busy {{
        background: {HAZARD_AMBER};
    }}
    #se-editor-dialog .se-tools-label {{
        width: 100%;
        color: {ACCENT_SOFT};
        padding: 0 1;
        margin-top: 1;
    }}
    #se-editor-dialog #se-editor-tools {{
        height: auto;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        padding: 1;
    }}
    #se-editor-dialog #se-editor-tools .se-editor-tool-group {{
        height: auto;
        width: 100%;
        grid-size: 4;
        grid-rows: 1;
        grid-gutter: 0 1;
    }}
    #se-editor-dialog .se-field-hint {{
        width: 1fr;
        color: #666;
        padding: 0 1;
        height: 1;
    }}
    #se-editor-dialog TextArea {{
        height: 1fr;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: #e5e5e5;
    }}
    #se-editor-dialog TextArea:focus {{
        border: solid {ACCENT_SOFT};
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
        color: {ACCENT};
    }}
    #se-editor-dialog .se-editor-footer Button.-primary {{
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    #se-editor-dialog #se-editor-usage {{
        height: 1;
        width: auto;
        padding: 0 1;
    }}
    #se-editor-dialog #se-editor-color {{
        height: 1;
        width: auto;
        padding: 0 1;
    }}
    #se-editor-dialog .se-hidden {{
        display: none;
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
        working_dir: Path,
        provider=None,
        model: str = "",
        provider_name: str = "",
        identifier: str = "",
    ) -> None:
        super().__init__()
        self._category = category
        self._scope = scope
        self._creating = creating
        self._item = item
        self._working_dir = working_dir
        self._initial_id = identifier or (item.identifier if item else "")
        self._initial_body = (item.body if item else category.new_template)
        self._initial_extra = dict(item.extra) if item else {}
        self._provider = provider
        self._model = model
        self._provider_name = provider_name
        self._generating = False
        self._spinner_timer = None
        self._spinner_index = 0

    def compose(self) -> ComposeResult:
        verb = "NEW" if self._creating else "EDIT"
        header = f"  ▰  {verb} · {self._category.label} · {self._scope.upper()} SCOPE"
        with Container(id="se-editor-dialog"):
            yield Static(header, classes="se-editor-header")
            yield Static(
                "  Esc cancel · Ctrl+S save",
                classes="se-editor-subheader",
            )
            yield from self._compose_fields()
            with Horizontal(classes="se-prompt-row"):
                yield Input(
                    placeholder=self._llm_placeholder(),
                    id="se-editor-llm-prompt",
                )
                # Same flow for both creating and editing: clicking opens
                # the fuzzy model picker, then streams the result into the
                # body. The label flips based on intent so the user knows
                # whether they're getting a fresh body or an edit.
                yield Button(
                    "◆ Generate" if self._creating else "◆ Edit",
                    id="se-editor-generate",
                )
            yield TextArea(self._initial_body, id="se-editor-body")
            with Horizontal(classes="se-editor-footer"):
                yield Button("Cancel", id="se-editor-cancel")
                yield Button("Save", id="se-editor-save", classes="-primary")

    def _compose_fields(self) -> ComposeResult:
        is_agent = self._category.key == "agents"
        with Horizontal(classes="se-field-row"):
            yield Label(
                "AGENT ID" if is_agent else "ID",
                classes="se-field-label",
            )
            yield Input(
                value=self._initial_id,
                placeholder="" if is_agent else self._id_placeholder(),
                id="se-editor-id",
                disabled=not self._creating,
            )
        if is_agent:
            with Horizontal(classes="se-field-row"):
                yield Label("MODEL ID", classes="se-field-label")
                yield Input(
                    value=self._initial_extra_model_only(),
                    placeholder="",
                    id="se-editor-model-id",
                )
            yield Static(
                "[dim]Optional — leave empty to use the session model.[/dim]",
                classes="se-field-hint",
                markup=True,
            )

            # ── USAGE: 3-way toggle ─────────────────────────────
            initial_usage = self._initial_usage()
            yield Static(
                "USAGE  [dim](main = tab/picker only · sub = spawnable by sub_agent · both)[/dim]",
                classes="se-tools-label",
                markup=True,
            )
            with Horizontal(id="se-editor-usage"):
                for value in ("main", "sub", "both"):
                    yield _UsageToggle(value, selected=(value == initial_usage))

            # ── COLOR: row of swatches — main + both only ──────
            # Build classes and set hidden state before yielding to avoid
            # duplicate widget IDs (yield + with block would mount twice).
            color_label_classes = "se-tools-label"
            color_row = Horizontal(id="se-editor-color")
            if initial_usage == "sub":
                color_label_classes += " se-hidden"
                color_row.add_class("se-hidden")

            yield Static(
                "COLOR  [dim](badge accent in picker / info bar)[/dim]",
                classes=color_label_classes,
                id="se-editor-color-label",
                markup=True,
            )
            initial_color = str(self._initial_extra.get("color", "") or "")
            with color_row:
                for hex_value, _label in AGENT_COLOR_PALETTE:
                    yield _ColorSwatch(
                        hex_value,
                        selected=(hex_value == initial_color),
                    )

            yield Static("ALLOWED TOOLS",
                         classes="se-tools-label", markup=True)
            selected = set(self._initial_extra.get("allowed_tools", []))
            all_tools = inventory.all_tool_names(self._working_dir)
            # Empty allowed_tools means "all tools" — show them all as ON.
            all_on = not selected
            from taui.tools.groups import resolve_groups_for_names
            groups = resolve_groups_for_names(all_tools)
            with Vertical(id="se-editor-tools"):
                for group in sorted(groups):
                    members = groups[group]
                    sel_count = sum(
                        1 for n in members if all_on or n in selected
                    )
                    yield _ToolGroupToggle(
                        group, selected=sel_count, total=len(members),
                    )
                    with Grid(classes="se-editor-tool-group"):
                        for name in members:
                            yield _ToolToggle(
                                name,
                                all_on or name in selected,
                                group=group,
                            )

    def _initial_usage(self) -> str:
        """Read the initial usage value from the extra dict, defaulting to 'both'."""
        from taui.self_edit.store import AGENT_USAGE_VALUES

        raw = str(self._initial_extra.get("usage", "") or "").strip().lower()
        if raw in AGENT_USAGE_VALUES:
            return raw
        # Back-compat: read the legacy boolean if present.
        if bool(self._initial_extra.get("subagent_only", False)):
            return "sub"
        return "both"

    def _initial_extra_model_only(self) -> str:
        """For the agent MODEL ID field — combined 'provider/model' string.

        Defaults to empty (the user said: empty by default, optional).
        """
        provider = str(self._initial_extra.get("provider", "")).strip()
        model = str(self._initial_extra.get("model", "")).strip()
        if not provider and not model:
            return ""
        return "/".join(p for p in (provider, model) if p)

    def _initial_model_id(self) -> str:
        """Combined provider/model string used as a single model selector."""
        provider = str(self._initial_extra.get("provider", "")).strip()
        model = str(self._initial_extra.get("model", "")).strip()
        if not provider and not model:
            # Pre-fill with the current session's model so the user sees
            # which model Generate will use by default.
            return self._provider_model_label()
        return "/".join(p for p in (provider, model) if p)

    def _id_placeholder(self) -> str:
        if self._category.key == "agents":
            return "3-letter UPPERCASE id (e.g. RDR)"
        if self._category.key == "skills":
            return "kebab-case skill name"
        if self._category.key == "mcp":
            return "server name (no spaces)"
        return "identifier"

    def _llm_placeholder(self) -> str:
        if self._creating:
            return {
                "agents": "describe the agent's job — eg. 'reviews TypeScript PRs for type safety'",
                "skills": "describe the skill — eg. 'recipes for migrating SQLAlchemy models'",
                "commands": "describe the command — eg. 'prints current branch and files'",
                "tools": "describe the tool — eg. 'calls a local HTTP endpoint and returns JSON'",
                "prompts": "describe the prompt — eg. 'explains a Python traceback'",
                "mcp": "describe the MCP server — eg. 'wraps the github CLI'",
            }.get(self._category.key, "describe what you want")
        return "describe the edit — eg. 'make this terser' or 'add a step about logging'"

    def _action_label(self) -> str:
        return "◆ Generate" if self._creating else "◆ Edit"

    def _provider_model_label(self) -> str:
        parts = [p for p in (self._provider_name, self._model) if p]
        return "/".join(parts)

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
        elif event.button.id == "se-editor-generate":
            self._start_llm_generation()
        else:
            self.dismiss(None)

    @on(_UsageToggle.Changed)
    def _on_usage_changed(self, event: _UsageToggle.Changed) -> None:
        """Update the active segment and show/hide the colour row."""
        event.stop()
        for toggle in self.query(_UsageToggle):
            toggle.set_active(toggle.value == event.value)
        try:
            color_row = self.query_one("#se-editor-color", Horizontal)
            color_label = self.query_one("#se-editor-color-label", Static)
        except Exception:
            return
        if event.value == "sub":
            color_row.add_class("se-hidden")
            color_label.add_class("se-hidden")
        else:
            color_row.remove_class("se-hidden")
            color_label.remove_class("se-hidden")

    @on(_ColorSwatch.Changed)
    def _on_color_changed(self, event: _ColorSwatch.Changed) -> None:
        event.stop()
        for swatch in self.query(_ColorSwatch):
            swatch.set_active(swatch.value == event.value)

    @on(_ToolGroupToggle.Changed)
    def _on_group_toggled(self, event: _ToolGroupToggle.Changed) -> None:
        event.stop()
        for toggle in self.query(_ToolToggle):
            if toggle.group == event.group:
                toggle.set_selected(event.select_all)
        self._refresh_group_headers()

    @on(_ToolToggle.Changed)
    def _on_tool_toggled(self, event: _ToolToggle.Changed) -> None:
        event.stop()
        self._refresh_group_headers()

    def _refresh_group_headers(self) -> None:
        groups: dict[str, tuple[int, int]] = {}
        for toggle in self.query(_ToolToggle):
            sel, total = groups.get(toggle.group, (0, 0))
            groups[toggle.group] = (
                sel + (1 if toggle.is_selected else 0),
                total + 1,
            )
        for header in self.query(_ToolGroupToggle):
            sel, total = groups.get(header.group, (0, 0))
            header.set_counts(selected=sel, total=total)

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
                toggles = list(self.query(_ToolToggle))
                allowed_tools = [t.tool_name for t in toggles if t.is_selected]
            except Exception:
                allowed_tools = list(self._initial_extra.get("allowed_tools", []))

            try:
                provider_str, model_str = _split_model_id(
                    self.query_one("#se-editor-model-id", Input).value.strip()
                )
            except Exception:
                provider_str, model_str = "", ""
            # Usage + color come from the toggle widgets.
            try:
                usage = next(
                    t.value for t in self.query(_UsageToggle) if "-on" in t.classes
                )
            except StopIteration:
                usage = self._initial_usage()
            try:
                color = next(
                    s.value for s in self.query(_ColorSwatch) if "-on" in s.classes
                )
            except StopIteration:
                color = str(self._initial_extra.get("color", "") or "")
            if usage == "sub":
                color = ""
            extra = {
                "name": ident,
                "provider": provider_str,
                "model": model_str,
                "allowed_tools": allowed_tools,
                "usage": usage,
                "color": color,
            }
        self.dismiss(
            {
                "identifier": ident,
                "body": body,
                "extra": extra,
            }
        )

    # ── LLM-assisted generation ─────────────────────────────────

    def _start_llm_generation(self) -> None:
        if self._generating:
            return
        if self._provider is None:
            self._flash_subheader("LLM not configured — type body manually.")
            return
        try:
            prompt_input = self.query_one("#se-editor-llm-prompt", Input)
        except Exception:
            return
        user_brief = prompt_input.value.strip()
        if not user_brief:
            verb = "Generate" if self._creating else "Edit"
            self._flash_subheader(
                f"Type a one-line brief, then click {verb}."
            )
            return
        default_model = self._effective_model_id()
        pairs = _available_models(self._provider_name)
        if default_model and default_model not in {m for m, _ in pairs}:
            pairs = [(default_model, self._provider_name)] + pairs
        models = [m for m, _ in pairs]
        provider_of = {m: p for m, p in pairs}

        def after(picked: str | None) -> None:
            if not picked:
                return
            self._generating = True
            self._start_spinner()
            self._generate_worker(user_brief, picked)

        if not models:
            # Fall back to whatever's in the model-id field if catalog lookup
            # failed (offline, unknown provider, etc.)
            if not default_model:
                self._flash_subheader(
                    "No model configured — fill the model id field."
                )
                return
            after(default_model)
            return

        self.app.push_screen(
            _ModelPicker(
                models=models,
                default=default_model,
                provider_of=provider_of,
            ),
            after,
        )

    def _effective_model_id(self) -> str:
        """Pre-seed value for the model picker.

        For agents, fall back to the agent's MODEL ID field. For other
        categories there's no editor-level model field, so we use the
        session's current model.
        """
        if self._category.key == "agents":
            try:
                raw = self.query_one("#se-editor-model-id", Input).value.strip()
            except Exception:
                raw = ""
            if raw:
                _, model = _split_model_id(raw)
                return model or raw
        return self._model

    _SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def _start_spinner(self) -> None:
        try:
            btn = self.query_one("#se-editor-generate", Button)
        except Exception:
            return
        btn.add_class("-busy")
        self._spinner_index = 0
        verb = "Generating…" if self._creating else "Editing…"
        btn.label = f"{self._SPINNER_FRAMES[0]} {verb}"
        # Tick every 80ms — gives a smooth braille-spinner rotation.
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _tick_spinner(self) -> None:
        try:
            btn = self.query_one("#se-editor-generate", Button)
        except Exception:
            return
        self._spinner_index = (self._spinner_index + 1) % len(self._SPINNER_FRAMES)
        verb = "Generating…" if self._creating else "Editing…"
        btn.label = f"{self._SPINNER_FRAMES[self._spinner_index]} {verb}"

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None
        try:
            btn = self.query_one("#se-editor-generate", Button)
            btn.label = self._action_label()
            btn.remove_class("-busy")
        except Exception:
            pass

    def _flash_subheader(self, text: str) -> None:
        try:
            self.query_one(".se-editor-subheader", Static).update(f"  {text}")
        except Exception:
            pass

    @work(exclusive=True, group="self_edit_modal_generate")
    async def _generate_worker(self, user_brief: str, model_id: str) -> None:
        await self._do_generate(user_brief, model_id)

    async def _do_generate(self, user_brief: str, model_id: str) -> None:
        """Body of the generation worker — separate so tests can call it."""
        current_body = ""
        if not self._creating:
            try:
                current_body = self.query_one("#se-editor-body", TextArea).text
            except Exception:
                current_body = self._initial_body
        prompt = _build_generation_prompt(
            self._category.key,
            user_brief,
            current_body=current_body if not self._creating else None,
        )
        body = ""
        try:
            # Providers serialize messages by JSON-dumping the request body,
            # which means we must hand them plain dicts — Message dataclasses
            # would crash with "Object of type Message is not JSON serializable".
            messages = [{"role": "user", "content": prompt}]
            async for event in self._provider.stream_text(
                messages, model_id, temperature=0.2
            ):
                if event.type == "text_delta" and event.delta:
                    body += event.delta
            body = _strip_code_fence(body).strip() + "\n"
        except Exception as exc:
            msg = str(exc).split("\n", 1)[0][:180]
            self._flash_subheader(f"LLM error ({model_id}): {msg}")
            self._generating = False
            self._stop_spinner()
            return

        try:
            area = self.query_one("#se-editor-body", TextArea)
            area.text = body
            area.focus()
            verb = "Generated" if self._creating else "Edited"
            self._flash_subheader(
                f"{verb}. Review and tweak, then Ctrl+S to save."
            )
        except Exception:
            pass
        finally:
            self._generating = False
            self._stop_spinner()


def _build_generation_prompt(
    category_key: str,
    user_brief: str,
    *,
    current_body: str | None = None,
) -> str:
    """Per-category prompt template that gets sent to the LLM.

    If `current_body` is provided, build an edit prompt — instruct the
    model to revise the existing body according to the user's brief and
    return the full updated body. Otherwise build a create prompt.
    """
    common = (
        "Output ONLY the file body, no surrounding explanation, no code fences. "
        "Be concise. Use the exact format described."
    )
    if current_body is not None:
        category_hint = {
            "agents": "a taui agent system prompt (plain markdown).",
            "skills": "a SKILL.md (YAML frontmatter + markdown body).",
            "commands": "a Python slash-command module.",
            "tools": "a Python tool extension module.",
            "prompts": "a markdown prompt fragment.",
            "mcp": "a TOML `[servers.NAME]` block.",
        }.get(category_key, "the file body.")
        return (
            f"{common}\n\n"
            f"You are editing {category_hint}\n"
            f"User instruction:\n  {user_brief}\n\n"
            "Apply the instruction and return the COMPLETE updated body. "
            "Keep everything not affected by the instruction unchanged.\n\n"
            "Current body:\n"
            "---\n"
            f"{current_body.rstrip()}\n"
            "---"
        )
    if category_key == "agents":
        return (
            f"{common}\n\n"
            "Write a system prompt for a taui agent profile. The agent should:\n"
            f"  {user_brief}\n\n"
            "Format: plain markdown. 5-15 lines. Start with a single-sentence "
            "role description, then a short 'Guidelines' bullet list."
        )
    if category_key == "skills":
        return (
            f"{common}\n\n"
            "Write a SKILL.md file. The skill should:\n"
            f"  {user_brief}\n\n"
            "Format: YAML frontmatter with `name` and `description` fields, then "
            "markdown body with step-by-step instructions. No code fences around "
            "the document itself."
        )
    if category_key == "commands":
        return (
            f"{common}\n\n"
            "Write a Python file that defines a taui slash command. The command "
            f"should: {user_brief}\n\n"
            "Format: a dataclass class with `name`, `description`, `accepts_args` "
            "attributes and an `async def execute(self, ctx)` returning "
            "`CommandResult.ok(...)`. Import: "
            "`from taui.commands.base import CommandResult`."
        )
    if category_key == "tools":
        return (
            f"{common}\n\n"
            "Write a Python module that defines a taui tool extension. The tool "
            f"should: {user_brief}\n\n"
            "Format: a class with `name`, `description`, `schema` (JSON schema "
            "for arguments) and an `async def execute(self, arguments)` returning "
            "`ToolResult.ok(...)`. Import: `from taui.tools.base import ToolResult`."
        )
    if category_key == "prompts":
        return (
            f"{common}\n\n"
            "Write a reusable prompt fragment. Topic:\n"
            f"  {user_brief}\n\n"
            "Format: plain markdown. Direct second-person voice. No frontmatter."
        )
    if category_key == "mcp":
        return (
            f"{common}\n\n"
            "Write a TOML block configuring an MCP server. Description:\n"
            f"  {user_brief}\n\n"
            "Format: `[servers.NAME]` header (you choose a sensible NAME), then "
            "`command = ...` and `args = [...]` lines. Optionally `env = {...}`."
        )
    return f"{common}\n\n{user_brief}"


def _available_model_ids(provider_name: str) -> list[str]:
    """Backward-compat shim — returns ids only. Prefer `_available_models`."""
    return [mid for mid, _provider in _available_models(provider_name)]


def _available_models(provider_name: str) -> list[tuple[str, str]]:
    """Return (model_id, provider_name) tuples for the generation picker.

    Scoped to the *current* session provider: the editor only has access
    to the session's wired-up provider instance, so offering models from
    other providers would just send a request the wrong API can't honor
    (which surfaces as "LLM error: 500 Internal Server Error"). Best-
    effort — returns an empty list if the catalog lookup fails.
    """
    if not provider_name:
        return []
    try:
        from taui.llm_provider.models import list_models
    except Exception:
        return []

    pairs: list[tuple[str, str]] = []
    try:
        for entry in list_models(provider_name):
            mid = str(entry.get("id", "")).strip()
            if mid:
                pairs.append((mid, provider_name))
    except Exception:
        pass
    return pairs


def _split_model_id(raw: str) -> tuple[str, str]:
    """Split 'provider/model' into (provider, model). One-part falls into model."""
    raw = raw.strip()
    if not raw:
        return "", ""
    if "/" in raw:
        provider, _, model = raw.partition("/")
        return provider.strip(), model.strip()
    return "", raw


def _strip_code_fence(text: str) -> str:
    """Strip a leading ```lang and trailing ``` if the model wrapped output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[: -3]
    return stripped


# ── Confirm delete sub-modal ────────────────────────────────────────


class _ConfirmDelete(ModalScreen[bool]):
    DEFAULT_CSS = f"""
    _ConfirmDelete {{
        align: center middle;
        background: $background 70%;
    }}
    #se-confirm {{
        width: 60;
        height: auto;
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 1 2;
    }}
    #se-confirm Static {{
        color: {ACCENT_SOFT};
    }}
    #se-confirm .se-confirm-title {{
        color: {HAZARD_AMBER};
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
        color: {ACCENT};
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
            yield Static("⚠ Delete item", classes="se-confirm-title")
            yield Static(f"Delete [bold]{self._label}[/bold]?", markup=True)
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


# ── Prefix editor sub-modal ─────────────────────────────────────────


class _PrefixEditor(ModalScreen[str | None]):
    """Simple single-character input for editing a prefix setting."""

    DEFAULT_CSS = f"""
    _PrefixEditor {{
        align: center middle;
        background: $background 70%;
    }}
    #se-prefix-dialog {{
        width: 52;
        height: auto;
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 1 2;
    }}
    #se-prefix-dialog .se-prefix-title {{
        color: {ACCENT};
        text-style: bold;
        margin: 0 0 1 0;
    }}
    #se-prefix-dialog .se-prefix-label {{
        color: {ACCENT_SOFT};
        margin: 0 0 0 0;
    }}
    #se-prefix-dialog Input {{
        width: 100%;
        height: 3;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: {ACCENT};
        margin: 0 0 1 0;
    }}
    #se-prefix-dialog Input:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-prefix-dialog .se-prefix-hint {{
        color: #666;
        height: 1;
        margin: 0 0 1 0;
    }}
    #se-prefix-dialog Horizontal {{
        height: 1;
        align-horizontal: right;
    }}
    #se-prefix-dialog Button {{
        margin: 0 0 0 1;
        border: none;
        padding: 0 1;
        height: 1;
        min-width: 0;
        background: {GRID_GREY};
        color: {ACCENT};
    }}
    #se-prefix-dialog Button.-primary {{
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    """

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, *, label: str, current_value: str) -> None:
        super().__init__()
        self._label = label
        self._current = current_value

    def compose(self) -> ComposeResult:
        with Container(id="se-prefix-dialog"):
            yield Static(f"◆ EDIT · {self._label}", classes="se-prefix-title")
            yield Static("Prefix character:", classes="se-prefix-label")
            yield Input(value=self._current, max_length=2, id="se-prefix-input")
            yield Static(
                "[dim]Single character. Esc cancel · Ctrl+S save[/dim]",
                classes="se-prefix-hint",
                markup=True,
            )
            with Horizontal():
                yield Button("Cancel", id="se-prefix-cancel")
                yield Button("Save", id="se-prefix-save", classes="-primary")

    def on_mount(self) -> None:
        try:
            self.query_one("#se-prefix-input", Input).focus()
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
        elif event.key == "enter":
            event.stop()
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "se-prefix-save":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        try:
            value = self.query_one("#se-prefix-input", Input).value
        except Exception:
            self.dismiss(None)
            return
        if not value:
            return
        self.dismiss(value)


# ── String / int editor sub-modal ───────────────────────────────────


class _StringEditor(ModalScreen[str | None]):
    """Generic single-line input for editing a string or integer setting."""

    DEFAULT_CSS = f"""
    _StringEditor {{
        align: center middle;
        background: $background 70%;
    }}
    #se-str-dialog {{
        width: 60;
        height: auto;
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 1 2;
    }}
    #se-str-dialog .se-str-title {{
        color: {ACCENT};
        text-style: bold;
        margin: 0 0 1 0;
    }}
    #se-str-dialog .se-str-label {{
        color: {ACCENT_SOFT};
        margin: 0 0 0 0;
    }}
    #se-str-dialog Input {{
        width: 100%;
        height: 3;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: {ACCENT};
        margin: 0 0 1 0;
    }}
    #se-str-dialog Input:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-str-dialog .se-str-hint {{
        color: #666;
        height: 1;
        margin: 0 0 1 0;
    }}
    #se-str-dialog Horizontal {{
        height: 1;
        align-horizontal: right;
    }}
    #se-str-dialog Button {{
        margin: 0 0 0 1;
        border: none;
        padding: 0 1;
        height: 1;
        min-width: 0;
        background: {GRID_GREY};
        color: {ACCENT};
    }}
    #se-str-dialog Button.-primary {{
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    """

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, *, label: str, current_value: str, hint: str = "") -> None:
        super().__init__()
        self._label = label
        self._current = current_value
        self._hint = hint or "Esc cancel · Ctrl+S save"

    def compose(self) -> ComposeResult:
        with Container(id="se-str-dialog"):
            yield Static(f"◆ EDIT · {self._label}", classes="se-str-title")
            yield Static("Value:", classes="se-str-label")
            yield Input(value=self._current, id="se-str-input")
            yield Static(
                f"[dim]{self._hint}[/dim]",
                classes="se-str-hint",
                markup=True,
            )
            with Horizontal():
                yield Button("Cancel", id="se-str-cancel")
                yield Button("Save", id="se-str-save", classes="-primary")

    def on_mount(self) -> None:
        try:
            self.query_one("#se-str-input", Input).focus()
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
        elif event.key == "enter":
            event.stop()
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "se-str-save":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        try:
            value = self.query_one("#se-str-input", Input).value
        except Exception:
            self.dismiss(None)
            return
        self.dismiss(value)


# ── General settings panel ───────────────────────────────────────────


class _SettingRow(Static):
    """A single focusable/highlightable row in the general settings panel."""

    DEFAULT_CSS = f"""
    _SettingRow {{
        height: 1;
        width: 100%;
        padding: 0 1;
        color: {ACCENT_SOFT};
    }}
    _SettingRow.-highlighted {{
        background: {ACCENT} 20%;
        color: {ACCENT};
        text-style: bold;
    }}
    _SettingRow.-section-header {{
        color: {ACCENT};
        text-style: bold;
        margin-top: 1;
        background: transparent;
    }}
    """

    def __init__(
        self,
        setting_key: str,
        label: str,
        value: object,
        *,
        is_header: bool = False,
        section_name: str = "",
    ) -> None:
        super().__init__()
        self.setting_key = setting_key
        self._label = label
        self._value = value
        self._is_header = is_header
        self._section_name = section_name
        if is_header:
            self.add_class("-section-header")

    def render(self) -> Text:
        if self._is_header:
            t = Text()
            t.append(f"─── {self._section_name} ", style=f"bold {ACCENT}")
            remaining = max(0, 58 - len(self._section_name) - 5)
            t.append("─" * remaining, style=f"bold {ACCENT}")
            return t
        width = 58
        left = f"  {self._label}"
        right = str(self._value)
        dots_space = max(3, width - len(left) - len(right))
        t = Text()
        t.append(left)
        t.append(" " + "·" * (dots_space - 2) + " ", style="dim #555555")
        t.append(right, style=ACCENT_SOFT)
        return t

    def set_value(self, value: object) -> None:
        self._value = value
        self.refresh()

    def highlight(self, on: bool) -> None:
        if self._is_header:
            return
        if on:
            self.add_class("-highlighted")
        else:
            self.remove_class("-highlighted")


class _GeneralSettings(VerticalScroll):
    """Scrollable settings panel for the General tab."""

    DEFAULT_CSS = f"""
    _GeneralSettings {{
        width: 100%;
        height: 1fr;
        background: {INNER_BG};
        border: solid {GRID_GREY};
        padding: 1 2;
    }}
    _GeneralSettings:focus {{
        border: solid {ACCENT_SOFT};
    }}
    """

    BINDINGS = [
        ("up", "move_up", "Up"),
        ("down", "move_down", "Down"),
        ("enter", "activate", "Edit/Toggle"),
        ("e", "activate", "Edit/Toggle"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows: list[_SettingRow] = []  # non-header rows only
        self._cursor: int = 0

    def compose(self) -> ComposeResult:
        return
        yield  # make this a generator

    def populate(self, values: dict[str, object]) -> None:
        """Remove old rows and mount fresh ones from current values."""
        for child in list(self.children):
            child.remove()
        self._rows = []
        self._cursor = 0

        for section_name, section_rows in inventory.GENERAL_SETTINGS_SECTIONS:
            self.mount(
                _SettingRow(
                    "",
                    "",
                    "",
                    is_header=True,
                    section_name=section_name,
                )
            )
            for key, label, _desc, _vtype in section_rows:
                raw = values.get(key, inventory._GENERAL_DEFAULTS.get(key, ""))
                display = inventory._format_general_value(raw)
                row = _SettingRow(key, label, display)
                self._rows.append(row)
                self.mount(row)

        if self._rows:
            self._rows[0].highlight(True)

    def action_move_up(self) -> None:
        if not self._rows:
            return
        self._rows[self._cursor].highlight(False)
        self._cursor = (self._cursor - 1) % len(self._rows)
        self._rows[self._cursor].highlight(True)
        self._rows[self._cursor].scroll_visible()

    def action_move_down(self) -> None:
        if not self._rows:
            return
        self._rows[self._cursor].highlight(False)
        self._cursor = (self._cursor + 1) % len(self._rows)
        self._rows[self._cursor].highlight(True)
        self._rows[self._cursor].scroll_visible()

    def action_activate(self) -> None:
        if not self._rows:
            return
        row = self._rows[self._cursor]
        self.post_message(_SettingActivated(row.setting_key))

    def current_key(self) -> str | None:
        if not self._rows:
            return None
        return self._rows[self._cursor].setting_key

    def refresh_row(self, key: str, new_display: str) -> None:
        for row in self._rows:
            if row.setting_key == key:
                row.set_value(new_display)
                break


class _SettingActivated(events.Event):
    """Posted by _GeneralSettings when the user activates a row."""

    def __init__(self, setting_key: str) -> None:
        super().__init__()
        self.setting_key = setting_key


# ── Inline edit panel (right pane) ───────────────────────────────────


class _InlineSaveRequested(events.Event):
    """Posted by _InlineEditor when the user clicks Save."""

    def __init__(self, payload: dict, creating: bool) -> None:
        super().__init__()
        self.payload = payload
        self.creating = creating


class _InlineEditor(Vertical):
    """Inline editor that lives in the right pane of the self-edit modal.

    Replaces the standalone _Editor sub-modal: shows the same fields
    (id, model, usage, color, allowed-tools, body) inline so the user
    can see and edit selection details without a second modal.
    """

    DEFAULT_CSS = f"""
    _InlineEditor {{
        height: 1fr;
        width: 100%;
        background: {INNER_BG};
        color: #b8b8b8;
        border: solid {GRID_GREY};
        padding: 1 1 0 1;
    }}
    _InlineEditor .se-inline-header-row {{
        height: 1;
        width: 100%;
        padding: 0 1;
    }}
    _InlineEditor .se-inline-header {{
        height: 1;
        width: 1fr;
        color: {ACCENT};
        text-style: bold;
        padding: 0;
    }}
    _InlineEditor .se-inline-header-row Button {{
        margin: 0 0 0 1;
        height: 1;
        min-height: 1;
        width: auto;
        min-width: 8;
        border: none;
        padding: 0 2;
        background: {GRID_GREY};
        color: {ACCENT};
        content-align: center middle;
    }}
    _InlineEditor .se-inline-header-row Button.-primary {{
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    _InlineEditor .se-inline-hint {{
        height: 1;
        width: 100%;
        color: #666;
        padding: 0 1;
    }}
    _InlineEditor .se-inline-empty {{
        height: 1fr;
        width: 100%;
        color: #666;
        content-align: center middle;
    }}
    _InlineEditor .se-field-row {{
        height: 3;
        width: 100%;
        padding: 0;
    }}
    _InlineEditor .se-field-label {{
        width: 14;
        height: 3;
        color: {ACCENT_SOFT};
        content-align: left middle;
        padding: 1 1 0 1;
    }}
    _InlineEditor Input {{
        width: 1fr;
        height: 3;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: {ACCENT};
    }}
    _InlineEditor Input:focus {{
        border: solid {ACCENT_SOFT};
    }}
    _InlineEditor .se-prompt-row {{
        height: 1;
        width: 100%;
        padding: 0;
        margin: 1 0 0 0;
    }}
    _InlineEditor .se-inline-llm-prompt {{
        height: 1;
        border: none;
        padding: 0 1;
        background: {INNER_BG};
        width: 1fr;
    }}
    _InlineEditor .se-inline-llm-prompt:focus {{
        background: {INNER_BG};
        border: none;
    }}
    _InlineEditor .se-inline-generate {{
        margin: 0 0 0 1;
        height: 1;
        min-width: 0;
        border: none;
        padding: 0 2;
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    _InlineEditor .se-inline-generate.-busy {{
        background: {HAZARD_AMBER};
    }}
    _InlineEditor .se-tools-label {{
        width: 100%;
        color: {ACCENT_SOFT};
        padding: 0 1;
        margin-top: 1;
    }}
    _InlineEditor .se-tools-header {{
        height: 1;
        width: 100%;
        padding: 0 1;
        margin-top: 1;
    }}
    _InlineEditor .se-tools-header Static {{
        width: 1fr;
        color: {ACCENT_SOFT};
    }}
    _InlineEditor .se-tools-toggle {{
        height: 1;
        width: auto;
        padding: 0 2;
        color: #777;
        background: {INNER_BG};
        content-align: center middle;
    }}
    _InlineEditor .se-tools-toggle.-on {{
        color: {DEEP_BLACK};
        background: {ACCENT};
        text-style: bold;
    }}
    _InlineEditor .se-tools-toggle:hover {{
        color: {ACCENT};
    }}
    _InlineEditor .se-tools-toggle.-on:hover {{
        color: {DEEP_BLACK};
    }}
    _InlineEditor .se-inline-tools {{
        height: auto;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        padding: 1;
    }}
    _InlineEditor .se-inline-tools .se-editor-tool-group {{
        height: auto;
        width: 100%;
        grid-size: 3;
        grid-rows: 1;
        grid-gutter: 0 1;
    }}
    _InlineEditor .se-field-hint {{
        width: 1fr;
        color: #666;
        padding: 0 1;
        height: 1;
    }}
    _InlineEditor TextArea {{
        height: 1fr;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        color: #e5e5e5;
        margin-top: 1;
    }}
    _InlineEditor TextArea:focus {{
        border: solid {ACCENT_SOFT};
    }}
    _InlineEditor .se-inline-footer {{
        height: 1;
        width: 100%;
        margin: 1 0 0 0;
        align-horizontal: right;
    }}
    _InlineEditor .se-inline-footer Button {{
        margin: 0 0 0 1;
        height: 1;
        min-width: 0;
        border: none;
        padding: 0 2;
        background: {GRID_GREY};
        color: {ACCENT};
    }}
    _InlineEditor .se-inline-footer Button.-primary {{
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    _InlineEditor .se-inline-usage {{
        height: 1;
        width: auto;
        padding: 0 1;
    }}
    _InlineEditor .se-inline-color {{
        height: 1;
        width: auto;
        padding: 0 1;
    }}
    _InlineEditor .se-hidden {{
        display: none;
    }}
    _InlineEditor .se-inline-preview {{
        height: 1fr;
        width: 100%;
        color: #b8b8b8;
        padding: 0 1;
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._working_dir: Path | None = None
        self._category: inventory.Category | None = None
        self._scope: str = "global"
        self._provider = None
        self._model = ""
        self._provider_name = ""
        # Live state for the active form
        self._mode: str = "empty"  # empty | preview | edit | new
        self._item: inventory.Item | None = None
        self._creating: bool = False
        # Cached widget refs for the currently mounted form
        self._id_input: Input | None = None
        self._model_input: Input | None = None
        self._body_area: TextArea | None = None
        self._llm_input: Input | None = None
        self._gen_button: Button | None = None
        self._initial_extra: dict = {}
        # LLM generation state
        self._generating = False
        self._spinner_timer = None
        self._spinner_index = 0
        # Allowed-tools UI: whether to surface built-in tools in the grid.
        self._show_builtin_tools = False

    def compose(self) -> ComposeResult:
        yield Static(
            "(no item selected — press [b]n[/b] to create a new one)",
            classes="se-inline-empty",
            markup=True,
        )

    # ── Context wiring ──────────────────────────────────────────────

    def set_context(
        self,
        *,
        working_dir: Path,
        category: inventory.Category,
        scope: str,
        provider,
        model: str,
        provider_name: str,
    ) -> None:
        self._working_dir = working_dir
        self._category = category
        self._scope = scope
        self._provider = provider
        self._model = model
        self._provider_name = provider_name

    # ── Public state transitions ────────────────────────────────────

    def show_empty(self) -> None:
        self._mode = "empty"
        self._item = None
        self._creating = False
        self._rebuild()

    def show_item(self, item: inventory.Item | None) -> None:
        if item is None:
            self.show_empty()
            return
        self._item = item
        self._creating = False
        if (
            self._category is not None
            and self._category.key == "tools"
            and item.builtin
        ):
            self._mode = "preview"
        else:
            self._mode = "edit"
        self._initial_extra = dict(item.extra)
        self._rebuild()

    def start_new(self) -> None:
        if self._category is None:
            return
        self._item = None
        self._creating = True
        self._mode = "new"
        self._initial_extra = {}
        self._rebuild()
        try:
            if self._id_input is not None:
                self._id_input.focus()
        except Exception:
            pass

    # ── Rebuild ─────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        for child in list(self.children):
            child.remove()
        self._id_input = None
        self._model_input = None
        self._body_area = None
        self._llm_input = None
        self._gen_button = None

        if self._mode == "empty" or self._category is None:
            self.mount(
                Static(
                    "(no item selected — press [b]n[/b] to create a new one)",
                    classes="se-inline-empty",
                    markup=True,
                )
            )
            return

        if self._mode == "preview":
            item = self._item
            assert item is not None
            header = f"{item.path}"
            body = item.body
            if len(body) > 8000:
                body = body[:8000] + "\n… (truncated)"
            self.mount(
                Static(
                    f"[b {ACCENT}]{item.label}[/b {ACCENT}]  [dim]· read-only (builtin)[/dim]",
                    classes="se-inline-header",
                    markup=True,
                )
            )
            self.mount(
                Static(
                    f"[dim]{header}[/dim]",
                    classes="se-inline-hint",
                    markup=True,
                )
            )
            self.mount(Static(body, classes="se-inline-preview", markup=False))
            return

        # edit / new
        cat = self._category
        item = self._item
        creating = self._creating
        verb = "NEW" if creating else "EDIT"
        header_text = f"▰ {verb} · {cat.label} · {self._scope.upper()} SCOPE"
        header_row = Horizontal(classes="se-inline-header-row")
        self.mount(header_row)
        header_row.mount(
            Static(header_text, classes="se-inline-header", markup=False)
        )
        header_row.mount(Button("Reset", classes="se-inline-reset"))
        header_row.mount(Button("Save", classes="se-inline-save -primary"))

        # ID row
        is_agent = cat.key == "agents"
        id_row = Horizontal(classes="se-field-row")
        self.mount(id_row)
        id_row.mount(
            Label(
                "AGENT ID" if is_agent else "ID",
                classes="se-field-label",
            )
        )
        self._id_input = Input(
            value=item.identifier if item else "",
            placeholder=self._id_placeholder(),
            disabled=not creating,
            classes="se-inline-id",
        )
        id_row.mount(self._id_input)

        # Agent-specific fields
        if is_agent:
            model_row = Horizontal(classes="se-field-row")
            self.mount(model_row)
            model_row.mount(Label("MODEL ID", classes="se-field-label"))
            self._model_input = Input(
                value=self._initial_extra_model(),
                placeholder="",
                classes="se-inline-model-id",
            )
            model_row.mount(self._model_input)
            self.mount(
                Static(
                    "[dim]Optional — empty uses the session model.[/dim]",
                    classes="se-field-hint",
                    markup=True,
                )
            )

            # Usage toggle
            initial_usage = self._initial_usage()
            self.mount(
                Static(
                    "USAGE",
                    classes="se-tools-label",
                    markup=True,
                )
            )
            usage_row = Horizontal(classes="se-inline-usage")
            self.mount(usage_row)
            for value in ("main", "sub", "both"):
                usage_row.mount(
                    _UsageToggle(value, selected=(value == initial_usage))
                )

            # Color swatches
            color_label_classes = "se-tools-label"
            initial_color = str(self._initial_extra.get("color", "") or "")
            if initial_usage == "sub":
                color_label_classes += " se-hidden"
            self.mount(
                Static(
                    "COLOR  [dim](badge accent in picker / info bar)[/dim]",
                    classes=color_label_classes,
                    markup=True,
                )
            )
            color_row = Horizontal(classes="se-inline-color")
            if initial_usage == "sub":
                color_row.add_class("se-hidden")
            self.mount(color_row)
            for hex_value, _label in AGENT_COLOR_PALETTE:
                color_row.mount(
                    _ColorSwatch(hex_value, selected=(hex_value == initial_color))
                )

            # Allowed tools grid (with show-built-in toggle on top)
            selected = set(self._initial_extra.get("allowed_tools", []))
            all_tools: list[str] = []
            if self._working_dir is not None:
                all_tools = inventory.all_tool_names(self._working_dir)
            builtins = inventory.builtin_tool_names()
            all_on = not selected
            tools_header = Horizontal(classes="se-tools-header")
            self.mount(tools_header)
            tools_header.mount(Static("ALLOWED TOOLS", markup=False))
            tools_header.mount(
                _ShowBuiltinToggle(selected=self._show_builtin_tools)
            )
            from taui.tools.groups import resolve_groups_for_names
            groups = resolve_groups_for_names(all_tools)
            tools_container = Vertical(classes="se-inline-tools")
            self.mount(tools_container)
            for group in sorted(groups):
                members = groups[group]
                visible_members = [
                    n for n in members
                    if self._show_builtin_tools or n not in builtins
                ]
                sel_count = sum(
                    1 for n in visible_members if all_on or n in selected
                )
                header = _ToolGroupToggle(
                    group,
                    selected=sel_count,
                    total=len(visible_members),
                )
                tools_container.mount(header)
                # If no members are visible in this group (all were builtin and
                # hidden), hide the header too.
                if not visible_members:
                    header.display = False
                group_grid = Grid(classes="se-editor-tool-group")
                tools_container.mount(group_grid)
                for name in members:
                    toggle = _ToolToggle(
                        name, all_on or name in selected, group=group,
                    )
                    is_builtin = name in builtins
                    if is_builtin and not self._show_builtin_tools:
                        toggle.display = False
                    group_grid.mount(toggle)

        # LLM prompt + Generate/Edit button
        prompt_row = Horizontal(classes="se-prompt-row")
        self.mount(prompt_row)
        self._llm_input = Input(
            placeholder=self._llm_placeholder(),
            classes="se-inline-llm-prompt",
        )
        prompt_row.mount(self._llm_input)
        self._gen_button = Button(
            "◆ Generate" if creating else "◆ Edit",
            classes="se-inline-generate",
        )
        prompt_row.mount(self._gen_button)

        # Body editor
        initial_body = item.body if item else cat.new_template
        self._body_area = TextArea(initial_body, classes="se-inline-body")
        self.mount(self._body_area)

    # ── Helpers ─────────────────────────────────────────────────────

    def _id_placeholder(self) -> str:
        if self._category is None:
            return "identifier"
        if self._category.key == "agents":
            return "3-letter UPPERCASE id (e.g. RDR)"
        if self._category.key == "skills":
            return "kebab-case skill name"
        if self._category.key == "mcp":
            return "server name (no spaces)"
        return "identifier"

    def _llm_placeholder(self) -> str:
        if self._category is None:
            return ""
        if self._creating:
            return {
                "agents": "describe the agent's job — eg. 'reviews TypeScript PRs'",
                "skills": "describe the skill — eg. 'recipes for SQLAlchemy'",
                "commands": "describe the command — eg. 'prints current branch'",
                "tools": "describe the tool — eg. 'calls a local HTTP endpoint'",
                "prompts": "describe the prompt — eg. 'explains a traceback'",
                "mcp": "describe the MCP server — eg. 'wraps the github CLI'",
            }.get(self._category.key, "describe what you want")
        return "describe the edit — eg. 'make this terser'"

    def _initial_usage(self) -> str:
        from taui.self_edit.store import AGENT_USAGE_VALUES

        raw = str(self._initial_extra.get("usage", "") or "").strip().lower()
        if raw in AGENT_USAGE_VALUES:
            return raw
        if bool(self._initial_extra.get("subagent_only", False)):
            return "sub"
        return "both"

    def _initial_extra_model(self) -> str:
        provider = str(self._initial_extra.get("provider", "")).strip()
        model = str(self._initial_extra.get("model", "")).strip()
        if not provider and not model:
            return ""
        return "/".join(p for p in (provider, model) if p)

    # ── Event handlers ──────────────────────────────────────────────

    @on(_UsageToggle.Changed)
    def _on_usage_changed(self, event: _UsageToggle.Changed) -> None:
        event.stop()
        for toggle in self.query(_UsageToggle):
            toggle.set_active(toggle.value == event.value)
        try:
            color_row = self.query_one(".se-inline-color")
            color_label = None
            for static in self.query(Static):
                if "se-tools-label" in static.classes and "COLOR" in static.renderable.__str__():
                    color_label = static
                    break
        except Exception:
            return
        if event.value == "sub":
            color_row.add_class("se-hidden")
            if color_label is not None:
                color_label.add_class("se-hidden")
        else:
            color_row.remove_class("se-hidden")
            if color_label is not None:
                color_label.remove_class("se-hidden")

    @on(_ColorSwatch.Changed)
    def _on_color_changed(self, event: _ColorSwatch.Changed) -> None:
        event.stop()
        for swatch in self.query(_ColorSwatch):
            swatch.set_active(swatch.value == event.value)

    @on(_ShowBuiltinToggle.Changed)
    def _on_show_builtin_changed(self, event: _ShowBuiltinToggle.Changed) -> None:
        event.stop()
        self._show_builtin_tools = event.value
        builtins = inventory.builtin_tool_names()
        for toggle in self.query(_ToolToggle):
            if toggle.tool_name in builtins:
                toggle.display = event.value
        self._refresh_group_headers()

    @on(_ToolGroupToggle.Changed)
    def _on_group_toggled(self, event: _ToolGroupToggle.Changed) -> None:
        event.stop()
        builtins = inventory.builtin_tool_names()
        for toggle in self.query(_ToolToggle):
            if toggle.group != event.group:
                continue
            if (
                toggle.tool_name in builtins
                and not self._show_builtin_tools
            ):
                continue
            toggle.set_selected(event.select_all)
        self._refresh_group_headers()

    @on(_ToolToggle.Changed)
    def _on_tool_toggled(self, event: _ToolToggle.Changed) -> None:
        event.stop()
        self._refresh_group_headers()

    def _refresh_group_headers(self) -> None:
        """Sync each group header's count to the current child toggle state."""
        builtins = inventory.builtin_tool_names()
        groups: dict[str, tuple[int, int]] = {}
        for toggle in self.query(_ToolToggle):
            if (
                toggle.tool_name in builtins
                and not self._show_builtin_tools
            ):
                continue
            sel, total = groups.get(toggle.group, (0, 0))
            groups[toggle.group] = (
                sel + (1 if toggle.is_selected else 0),
                total + 1,
            )
        for header in self.query(_ToolGroupToggle):
            sel, total = groups.get(header.group, (0, 0))
            header.set_counts(selected=sel, total=total)
            header.display = total > 0

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        classes = event.button.classes
        if "se-inline-save" in classes:
            event.stop()
            self._submit()
        elif "se-inline-reset" in classes:
            event.stop()
            self._rebuild()
        elif "se-inline-generate" in classes:
            event.stop()
            self._start_llm_generation()

    def _submit(self) -> None:
        if self._id_input is None or self._body_area is None or self._category is None:
            return
        ident = self._id_input.value.strip()
        body = self._body_area.text
        if not ident:
            return
        if self._category.key == "agents":
            ident = ident.upper()
        extra: dict = {}
        if self._category.key == "agents":
            try:
                toggles = list(self.query(_ToolToggle))
                allowed_tools = [t.tool_name for t in toggles if t.is_selected]
            except Exception:
                allowed_tools = list(self._initial_extra.get("allowed_tools", []))
            provider_str, model_str = "", ""
            if self._model_input is not None:
                provider_str, model_str = _split_model_id(
                    self._model_input.value.strip()
                )
            try:
                usage = next(
                    t.value for t in self.query(_UsageToggle) if "-on" in t.classes
                )
            except StopIteration:
                usage = self._initial_usage()
            try:
                color = next(
                    s.value for s in self.query(_ColorSwatch) if "-on" in s.classes
                )
            except StopIteration:
                color = str(self._initial_extra.get("color", "") or "")
            if usage == "sub":
                color = ""
            extra = {
                "name": ident,
                "provider": provider_str,
                "model": model_str,
                "allowed_tools": allowed_tools,
                "usage": usage,
                "color": color,
            }
        payload = {"identifier": ident, "body": body, "extra": extra}
        self.post_message(_InlineSaveRequested(payload, self._creating))

    # ── LLM generation (reuses helpers from _Editor) ────────────────

    _SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def _start_llm_generation(self) -> None:
        if self._generating or self._llm_input is None or self._category is None:
            return
        if self._provider is None:
            return
        user_brief = self._llm_input.value.strip()
        if not user_brief:
            return
        default_model = self._effective_model_id()
        pairs = _available_models(self._provider_name)
        if default_model and default_model not in {m for m, _ in pairs}:
            pairs = [(default_model, self._provider_name)] + pairs
        models = [m for m, _ in pairs]
        provider_of = {m: p for m, p in pairs}

        def after(picked: str | None) -> None:
            if not picked:
                return
            self._generating = True
            self._start_spinner()
            self._generate_worker(user_brief, picked)

        if not models:
            if not default_model:
                return
            after(default_model)
            return

        self.app.push_screen(
            _ModelPicker(
                models=models,
                default=default_model,
                provider_of=provider_of,
            ),
            after,
        )

    def _effective_model_id(self) -> str:
        if (
            self._category is not None
            and self._category.key == "agents"
            and self._model_input is not None
        ):
            raw = self._model_input.value.strip()
            if raw:
                _, model = _split_model_id(raw)
                return model or raw
        return self._model

    def _start_spinner(self) -> None:
        if self._gen_button is None:
            return
        self._gen_button.add_class("-busy")
        self._spinner_index = 0
        verb = "Generating…" if self._creating else "Editing…"
        self._gen_button.label = f"{self._SPINNER_FRAMES[0]} {verb}"
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if self._gen_button is None:
            return
        self._spinner_index = (self._spinner_index + 1) % len(self._SPINNER_FRAMES)
        verb = "Generating…" if self._creating else "Editing…"
        self._gen_button.label = (
            f"{self._SPINNER_FRAMES[self._spinner_index]} {verb}"
        )

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None
        if self._gen_button is not None:
            self._gen_button.label = (
                "◆ Generate" if self._creating else "◆ Edit"
            )
            self._gen_button.remove_class("-busy")

    @work(exclusive=True, group="self_edit_inline_generate")
    async def _generate_worker(self, user_brief: str, model_id: str) -> None:
        await self._do_generate(user_brief, model_id)

    async def _do_generate(self, user_brief: str, model_id: str) -> None:
        if self._category is None or self._body_area is None:
            return
        current_body = "" if self._creating else self._body_area.text
        prompt = _build_generation_prompt(
            self._category.key,
            user_brief,
            current_body=current_body if not self._creating else None,
        )
        body = ""
        try:
            messages = [{"role": "user", "content": prompt}]
            async for event in self._provider.stream_text(
                messages, model_id, temperature=0.2
            ):
                if event.type == "text_delta" and event.delta:
                    body += event.delta
            body = _strip_code_fence(body).strip() + "\n"
        except Exception:
            self._generating = False
            self._stop_spinner()
            return
        try:
            if self._body_area is not None:
                self._body_area.text = body
                self._body_area.focus()
        except Exception:
            pass
        finally:
            self._generating = False
            self._stop_spinner()


# ── Main modal ──────────────────────────────────────────────────────


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
        background: {PANEL_BG};
        border: round {BORDER};
        padding: 0;
    }}
    #se-top-row {{
        height: auto;
        background: {PANEL_BG};
        padding: 0 2;
    }}
    #se-top-row #se-tabs-stack {{
        width: 1fr;
        height: auto;
    }}
    #se-top-row #se-tabs-stack .se-tabs-row {{
        width: 1fr;
        height: 1;
        align-horizontal: left;
    }}
    #se-top-row #se-tabs-stack .se-tabs-row _CategoryTab {{
        margin: 0 1 0 0;
    }}
    #se-top-row #se-scope-row {{
        width: auto;
        height: 1;
        align-horizontal: right;
    }}
    #se-top-row #se-scope-row _ScopeChip {{
        margin: 0 0 0 1;
    }}
    #se-scope-path {{
        height: 1;
        background: {PANEL_BG};
        color: {ACCENT_SOFT};
        padding: 0 2;
        text-align: right;
    }}
    #se-body {{
        height: 1fr;
        background: {PANEL_BG};
        padding: 0 1;
    }}
    #se-list-pane {{
        width: 34%;
        height: 1fr;
        padding: 0 1 0 0;
    }}
    #se-list-pane OptionList {{
        height: 1fr;
        width: 100%;
        background: {INNER_BG};
        color: {ACCENT};
        border: solid {GRID_GREY};
    }}
    #se-list-pane OptionList:focus {{
        border: solid {ACCENT_SOFT};
    }}
    #se-list-pane .option-list--option-highlighted {{
        background: {ACCENT} 20%;
        color: {ACCENT};
        text-style: bold;
    }}
    #se-list-pane #se-new-button {{
        margin: 1 0 1 0;
        height: 1;
        width: 100%;
        min-width: 0;
        border: none;
        padding: 0;
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
        content-align: center middle;
    }}
    #se-list-pane #se-list-builtin-toggle {{
        height: 1;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0;
        color: #777;
        background: {INNER_BG};
        content-align: center middle;
    }}
    #se-list-pane #se-list-builtin-toggle.-on {{
        color: {DEEP_BLACK};
        background: {ACCENT};
        text-style: bold;
    }}
    #se-list-pane #se-list-builtin-toggle:hover {{
        color: {ACCENT};
    }}
    #se-list-pane #se-list-builtin-toggle.-on:hover {{
        color: {DEEP_BLACK};
    }}
    #se-list-pane #se-new-button:hover {{
        background: {HAZARD_AMBER};
        color: {DEEP_BLACK};
    }}
    #se-list-pane #se-new-button:focus {{
        background: {HAZARD_AMBER};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    #se-edit-pane {{
        width: 1fr;
        height: 1fr;
        padding: 0 0 0 1;
    }}
    #se-footer {{
        height: 1;
        background: {PANEL_BG};
        color: {ACCENT_SOFT};
        padding: 0 2;
    }}
    #se-settings-pane {{
        width: 100%;
        height: 1fr;
        display: none;
        background: {PANEL_BG};
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
        # Row-aligned mapping: OptionList row index → underlying Item or None
        # (None marks a non-selectable header row used for the tools tree).
        self._row_items: list[inventory.Item | None] = []
        # Show built-in tools in the TOOLS category list. Default off so
        # the user's own tools are easier to scan; toggle re-includes them.
        self._show_builtin_in_list: bool = False

    @property
    def _category(self) -> inventory.Category:
        return inventory.CATEGORIES[self._category_index]

    def compose(self) -> ComposeResult:
        with Container(id="se-dialog"):
            with Horizontal(id="se-top-row"):
                with Vertical(id="se-tabs-stack"):
                    with Horizontal(classes="se-tabs-row", id="se-tabs-row-1"):
                        pass  # populated by _layout_tabs on mount/resize
                    with Horizontal(classes="se-tabs-row", id="se-tabs-row-2"):
                        pass
                with Horizontal(id="se-scope-row"):
                    yield _ScopeChip("global", active=self._scope == "global")
                    yield _ScopeChip("project", active=self._scope == "project")
            yield Static(
                f"{inventory.scope_root(self._working_dir, self._scope)}  ",
                id="se-scope-path",
            )
            with Horizontal(id="se-body"):
                with Vertical(id="se-list-pane"):
                    yield Button("✚ NEW", id="se-new-button")
                    list_toggle = _ListBuiltinToggle(
                        selected=self._show_builtin_in_list,
                    )
                    list_toggle.id = "se-list-builtin-toggle"
                    yield list_toggle
                    yield OptionList(id="se-options")
                with Vertical(id="se-edit-pane"):
                    yield _InlineEditor(id="se-inline")
                with Container(id="se-settings-pane"):
                    yield _GeneralSettings(id="se-general-settings")
            yield Static(
                "n new · e edit · d delete · ←→ category · tab scope · esc close",
                id="se-footer",
            )

    def on_mount(self) -> None:
        self._layout_tabs()
        self._refresh_items()
        if self._category.key != "general":
            try:
                self.query_one("#se-options", OptionList).focus()
            except Exception:
                pass

    def on_resize(self, event: events.Resize) -> None:
        self._layout_tabs()

    def _layout_tabs(self) -> None:
        """Distribute the category tabs across one or two rows.

        On wide terminals everything fits on row 1. On narrow ones we
        split the categories in half so the user can still see them all.
        """
        try:
            row1 = self.query_one("#se-tabs-row-1", Horizontal)
            row2 = self.query_one("#se-tabs-row-2", Horizontal)
        except Exception:
            return

        # Remove any existing tabs from both rows before re-populating.
        for tab in list(self.query(_CategoryTab)):
            tab.remove()

        # Rough char budget: padding (4) + ~2 chars margin/count, summed.
        approx_total = sum(len(c.label) + 8 for c in inventory.CATEGORIES)
        # Subtract space reserved for the scope chips on the right.
        available = (self.size.width or 120) - 24
        single_row = approx_total <= available

        if single_row:
            split = [list(inventory.CATEGORIES), []]
        else:
            mid = (len(inventory.CATEGORIES) + 1) // 2
            split = [
                list(inventory.CATEGORIES[:mid]),
                list(inventory.CATEGORIES[mid:]),
            ]

        counts = inventory.counts(self._working_dir)
        for row, cats in zip((row1, row2), split):
            for cat in cats:
                # General and tools are global-only; hide them in project scope.
                if (
                    self._scope == "project"
                    and cat.key in ("general", "tools")
                ):
                    continue
                idx = inventory.CATEGORIES.index(cat)
                tab = _CategoryTab(
                    cat.key,
                    cat.label,
                    counts.get(cat.key, {}).get(self._scope, 0),
                    active=(idx == self._category_index),
                )
                row.mount(tab)

    # ── Refresh ───────────────────────────────────────────────────

    def _refresh_items(self) -> None:
        is_general = self._category.key == "general"

        # Switch between standard list+inline-editor and settings panel.
        try:
            list_pane = self.query_one("#se-list-pane", Vertical)
            edit_pane = self.query_one("#se-edit-pane", Vertical)
            settings_pane = self.query_one("#se-settings-pane")
        except Exception:
            list_pane = edit_pane = settings_pane = None

        if list_pane is not None:
            list_pane.display = not is_general
            edit_pane.display = not is_general
            settings_pane.display = is_general

        if is_general:
            self._refresh_general_panel()
            self._refresh_chrome()
            return

        self._items = inventory.list_items(
            self._working_dir, self._category.key, self._scope
        )
        if (
            self._category.key == "tools"
            and not self._show_builtin_in_list
        ):
            self._items = [it for it in self._items if not it.builtin]
        try:
            opts = self.query_one("#se-options", OptionList)
        except Exception:
            return
        # Show the list-level "show built-in" toggle only on the TOOLS tab.
        try:
            list_toggle = self.query_one(
                "#se-list-builtin-toggle", _ListBuiltinToggle
            )
            list_toggle.display = self._category.key == "tools"
        except Exception:
            pass
        opts.clear_options()
        self._row_items = []
        if not self._items:
            opts.add_option(
                Option(
                    Text("(empty — press 'n' to create one)", style=f"italic {GRID_GREY}"),
                    id="__empty__",
                    disabled=True,
                )
            )
            self._row_items.append(None)
        elif self._category.key == "tools":
            # Tree view: group items by their canonical tool-group, render a
            # disabled "folder" header followed by indented children.
            from taui.tools.groups import resolve_groups_for_names

            names = [it.identifier for it in self._items]
            groups = resolve_groups_for_names(names)
            by_id: dict[str, inventory.Item] = {
                it.identifier: it for it in self._items
            }
            first_select_idx: int | None = None
            row = 0
            for group in sorted(groups):
                members = [
                    by_id[n] for n in groups[group] if n in by_id
                ]
                if not members:
                    continue
                opts.add_option(
                    Option(
                        Text(
                            f"▾ {group}  ({len(members)})",
                            style=f"bold {ACCENT_SOFT}",
                        ),
                        id=f"__group:{group}__",
                        disabled=True,
                    )
                )
                self._row_items.append(None)
                row += 1
                for item in members:
                    opt_id = (
                        f"builtin:{item.identifier}"
                        if item.builtin
                        else f"user:{item.identifier}"
                    )
                    opts.add_option(
                        Option(
                            self._render_tree_item_row(item),
                            id=opt_id,
                        )
                    )
                    self._row_items.append(item)
                    if first_select_idx is None:
                        first_select_idx = row
                    row += 1
            if first_select_idx is not None:
                opts.highlighted = first_select_idx
        else:
            for item in self._items:
                # ID must be unique within the OptionList — a user extension
                # file can share a name with a builtin tool (e.g. worktree.py
                # vs the WorktreeTool builtin), so disambiguate by builtin flag.
                opt_id = (
                    f"builtin:{item.identifier}"
                    if item.builtin
                    else f"user:{item.identifier}"
                )
                opts.add_option(
                    Option(self._render_item_row(item), id=opt_id)
                )
                self._row_items.append(item)
            opts.highlighted = 0
        self._sync_inline_panel()
        self._refresh_chrome()

    def _render_tree_item_row(self, item: inventory.Item) -> Text:
        """Indented variant of _render_item_row for the tools tree view."""
        text = Text()
        label_style = (
            f"bold {ACCENT_SOFT}" if item.builtin else f"bold {ACCENT}"
        )
        text.append("  └ ", style=GRID_GREY)
        text.append(f"{item.label:<20s}", style=label_style)
        suffix = " [builtin]" if item.builtin else ""
        text.append(f" {item.summary}{suffix}", style="#999999")
        return text

    def _refresh_general_panel(self) -> None:
        """Populate (or repopulate) the _GeneralSettings widget."""
        try:
            panel = self.query_one("#se-general-settings", _GeneralSettings)
        except Exception:
            return
        values = inventory._load_general_values()
        panel.populate(values)
        try:
            panel.focus()
        except Exception:
            pass

    def _refresh_chrome(self) -> None:
        counts = inventory.counts(self._working_dir)
        # Tabs may be spread across two rows on narrow terminals — iterate
        # them all and refresh count/active state by category key.
        for tab in self.query(_CategoryTab):
            cat = next(
                (c for c in inventory.CATEGORIES if c.key == tab.category_key),
                None,
            )
            if cat is None:
                continue
            tab._count = counts.get(cat.key, {}).get(self._scope, 0)
            idx = inventory.CATEGORIES.index(cat)
            if idx == self._category_index:
                tab.add_class("-active")
            else:
                tab.remove_class("-active")
            tab.refresh()
        try:
            scope_row = self.query_one("#se-scope-row", Horizontal)
            for chip in scope_row.query(_ScopeChip):
                if chip._scope == self._scope:
                    chip.add_class("-active")
                else:
                    chip.remove_class("-active")
        except Exception:
            pass
        try:
            path_label = self.query_one("#se-scope-path", Static)
            path_label.update(
                f"{inventory.scope_root(self._working_dir, self._scope)}  "
            )
        except Exception:
            pass
        try:
            new_btn = self.query_one("#se-new-button", Button)
            if self._category.key == "general":
                new_btn.display = False
            else:
                new_btn.display = True
        except Exception:
            pass

    def _render_item_row(self, item: inventory.Item) -> Text:
        text = Text()
        # Sub-only agents have no accent color (the picker doesn't expose
        # them and the COLOR option is hidden in the editor), so render
        # them gray to signal that the colour slot is unused.
        usage = ""
        if item.category == "agents":
            usage = str(item.extra.get("usage", "") or "").strip().lower()
        if item.builtin:
            label_style = f"bold {ACCENT_SOFT}"
        elif usage == "sub":
            label_style = "bold #777777"
        else:
            label_style = f"bold {ACCENT}"
        text.append(" ", style=ACCENT)
        text.append(f"{item.label:<22s}", style=label_style)

        # Agents: id + usage badge only (no name / model summary).
        if item.category == "agents":
            color = str(item.extra.get("color", "") or "").strip()
            if usage in ("main", "sub", "both"):
                badge_style = f"dim {color}" if color else "dim"
                text.append(f" [{usage}]", style=badge_style)
            return text

        # Non-agents: keep the summary line so users can scan descriptions.
        suffix = " [builtin]" if item.builtin else ""
        text.append(f" {item.summary}{suffix}", style="#999999")
        return text

    def _current_item(self) -> inventory.Item | None:
        try:
            opts = self.query_one("#se-options", OptionList)
        except Exception:
            return None
        idx = opts.highlighted
        if idx is None or idx < 0:
            return None
        # Prefer the row-aligned mapping (handles tree headers).
        if self._row_items and idx < len(self._row_items):
            return self._row_items[idx]
        if idx < len(self._items):
            return self._items[idx]
        return None

    def _sync_inline_panel(self) -> None:
        """Push the highlighted item (or empty state) into the inline editor."""
        try:
            inline = self.query_one("#se-inline", _InlineEditor)
        except Exception:
            return
        provider, model, provider_name = self._llm_handles()
        inline.set_context(
            working_dir=self._working_dir,
            category=self._category,
            scope=self._scope,
            provider=provider,
            model=model,
            provider_name=provider_name,
        )
        item = self._current_item()
        if item is None:
            inline.show_empty()
        else:
            inline.show_item(item)

    # ── Tab / scope clicks ─────────────────────────────────────────

    @on(_CategoryClicked)
    def _on_category_clicked(self, message: _CategoryClicked) -> None:
        for i, cat in enumerate(inventory.CATEGORIES):
            if cat.key == message.category_key:
                self._category_index = i
                break
        self._refresh_items()

    @on(_ScopeClicked)
    def _on_scope_clicked(self, message: _ScopeClicked) -> None:
        self._scope = message.scope
        self._refresh_items()

    @on(Button.Pressed, "#se-new-button")
    def _on_new_button(self, _: Button.Pressed) -> None:
        self.action_new_item()

    @on(_ListBuiltinToggle.Changed)
    def _on_list_builtin_changed(self, event: _ListBuiltinToggle.Changed) -> None:
        event.stop()
        self._show_builtin_in_list = event.value
        self._refresh_items()

    # ── Actions ───────────────────────────────────────────────────

    @on(OptionList.OptionHighlighted)
    def _on_option_highlighted(self, _: OptionList.OptionHighlighted) -> None:
        self._sync_inline_panel()

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id == "__empty__":
            self.action_new_item()
            return
        # Form is already inline — focus the body so the user can edit.
        self._focus_inline_body()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_next_scope(self) -> None:
        self._scope = "project" if self._scope == "global" else "global"
        self._bump_off_general()
        self._refresh_items()

    def action_set_global(self) -> None:
        self._scope = "global"
        self._refresh_items()

    def action_set_project(self) -> None:
        self._scope = "project"
        self._bump_off_general()
        self._refresh_items()

    def _bump_off_general(self) -> None:
        """If on a project-hidden category in project scope, move forward."""
        n = len(inventory.CATEGORIES)
        steps = 0
        while (
            self._scope == "project"
            and self._category.key in ("general", "tools")
            and steps < n
        ):
            self._category_index = (self._category_index + 1) % n
            steps += 1

    def action_next_category(self) -> None:
        n = len(inventory.CATEGORIES)
        self._category_index = (self._category_index + 1) % n
        steps = 0
        while (
            self._scope == "project"
            and self._category.key in ("general", "tools")
            and steps < n
        ):
            self._category_index = (self._category_index + 1) % n
            steps += 1
        self._refresh_items()

    def action_prev_category(self) -> None:
        n = len(inventory.CATEGORIES)
        self._category_index = (self._category_index - 1) % n
        steps = 0
        while (
            self._scope == "project"
            and self._category.key in ("general", "tools")
            and steps < n
        ):
            self._category_index = (self._category_index - 1) % n
            steps += 1
        self._refresh_items()

    def action_new_item(self) -> None:
        if self._category.key == "general":
            return
        try:
            inline = self.query_one("#se-inline", _InlineEditor)
        except Exception:
            return
        provider, model, provider_name = self._llm_handles()
        inline.set_context(
            working_dir=self._working_dir,
            category=self._category,
            scope=self._scope,
            provider=provider,
            model=model,
            provider_name=provider_name,
        )
        inline.start_new()

    def action_edit_item(self) -> None:
        if self._category.key == "general":
            self._edit_general_setting()
            return
        item = self._current_item()
        if item is None:
            self.action_new_item()
            return
        if item.builtin and self._category.key == "tools":
            # Built-in tools are read-only — preview only in the right pane.
            return
        # The form is already mounted inline; just focus its body.
        self._focus_inline_body()

    def _focus_inline_body(self) -> None:
        try:
            inline = self.query_one("#se-inline", _InlineEditor)
            if inline._body_area is not None:
                inline._body_area.focus()
        except Exception:
            pass

    @on(_InlineSaveRequested)
    def _on_inline_save(self, message: _InlineSaveRequested) -> None:
        message.stop()
        if self._category is None:
            return
        try:
            current_id = (
                self._current_item().identifier
                if self._current_item() is not None
                else ""
            )
            ident = message.payload["identifier"] or current_id
            inventory.save_item(
                self._working_dir,
                self._category.key,
                self._scope,
                ident,
                message.payload["body"],
                message.payload.get("extra"),
            )
        except Exception as exc:
            self.app.bell()
            self._toast(f"Save failed: {exc}")
            return
        # Refresh list, then re-select the saved item if possible.
        self._refresh_items()
        try:
            opts = self.query_one("#se-options", OptionList)
            rows = self._row_items or [it for it in self._items]
            for i, it in enumerate(rows):
                if it is not None and it.identifier == ident:
                    opts.highlighted = i
                    break
        except Exception:
            pass
        self._sync_inline_panel()
        self._toast(f"Saved {self._category.label.lower()} · {ident}")

    def _edit_general_setting(self) -> None:
        """Open an appropriate editor for the currently highlighted general setting."""
        try:
            panel = self.query_one("#se-general-settings", _GeneralSettings)
        except Exception:
            return
        key = panel.current_key()
        if key is None:
            return
        self._open_general_editor(key)

    @on(_SettingActivated)
    def _on_setting_activated(self, event: _SettingActivated) -> None:
        self._open_general_editor(event.setting_key)

    def _open_general_editor(self, key: str) -> None:
        """Dispatch to the right editor based on the setting type."""
        from taui.self_edit.inventory import (
            _GENERAL_DEFAULTS,
            _GENERAL_SETTINGS_MAP,
            _format_general_value,
            _load_general_values,
            save_general_setting,
        )

        if key not in _GENERAL_SETTINGS_MAP:
            return
        _path, vtype = _GENERAL_SETTINGS_MAP[key]
        values = _load_general_values()
        current = values.get(key, _GENERAL_DEFAULTS.get(key, ""))

        # Find the display label for this key.
        label = key
        for _section, rows in inventory.GENERAL_SETTINGS_SECTIONS:
            for row_key, row_label, _desc, _vt in rows:
                if row_key == key:
                    label = row_label
                    break

        def _save_and_refresh(new_value: object) -> None:
            try:
                save_general_setting(key, new_value)
            except Exception as exc:
                self.app.bell()
                self._toast(f"Save failed: {exc}")
                return
            # Update the panel row directly to avoid a full repopulate.
            try:
                panel = self.query_one("#se-general-settings", _GeneralSettings)
                panel.refresh_row(key, _format_general_value(new_value))
            except Exception:
                pass
            self._refresh_chrome()

        if vtype is bool:
            # Toggle immediately — no modal needed.
            _save_and_refresh(not bool(current))
            return

        if vtype is str and key in ("file_attach", "command"):
            # Single-char prefix: use the compact _PrefixEditor.
            def after_prefix(new_value: str | None) -> None:
                if new_value is None:
                    return
                _save_and_refresh(new_value)

            self.app.push_screen(
                _PrefixEditor(label=label, current_value=str(current)),
                after_prefix,
            )
            return

        # String or int: generic single-line editor.
        if vtype is int:
            hint = "Integer value. Esc cancel · Ctrl+S save"
        else:
            hint = "Esc cancel · Ctrl+S save"

        def after_str(new_value: str | None) -> None:
            if new_value is None:
                return
            if vtype is int:
                try:
                    coerced: object = int(new_value)
                except ValueError:
                    self.app.bell()
                    self._toast(f"'{new_value}' is not a valid integer.")
                    return
            else:
                coerced = new_value
            _save_and_refresh(coerced)

        self.app.push_screen(
            _StringEditor(label=label, current_value=str(current), hint=hint),
            after_str,
        )

    def action_delete_item(self) -> None:
        item = self._current_item()
        if item is None:
            return
        if self._category.key == "general":
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
            except Exception as exc:
                self.app.bell()
                self._toast(f"Delete failed: {exc}")
                return
            self._refresh_items()

        self.app.push_screen(confirm, after)

    def _toast(self, message: str) -> None:
        try:
            self.query_one("#se-footer", Static).update(
                f"[bold {HAZARD_AMBER}]{message}[/bold {HAZARD_AMBER}]"
            )
        except Exception:
            pass

    def _llm_handles(self):
        """Return (provider, model, provider_name) from the current session."""
        session = getattr(self.app, "_session", None)
        if session is None:
            return None, "", ""
        provider = getattr(session, "_provider", None)
        config = getattr(session, "config", None)
        model = ""
        provider_name = ""
        if config is not None:
            model = str(getattr(config, "model", "") or "")
            provider_name = str(getattr(config, "provider", "") or "")
        return provider, model, provider_name

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
