"""Self-edit modal — futuristic yellow console.

A single modal that exposes CRUD over every self-edit category (agents,
skills, commands, tools, prompts, MCP servers) across both scopes
(global, project). Used by Ctrl+E and `/self-edit`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
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
ACCENT = "#f0c808"        # bright hazard yellow — used for headings/highlights
ACCENT_SOFT = "#c9a300"   # warm yellow — body text accents
BORDER = "#5a4500"        # dark olive — subtle yellow border
PANEL_BG = "#0d0d0d"      # dialog background
INNER_BG = "#121212"      # slightly lighter for sub-panels
DEEP_BLACK = "#0a0a0a"
HAZARD_AMBER = "#ffae00"  # warning/destructive accent
GRID_GREY = "#2a2a2a"     # darker grey for inner borders


@dataclass(frozen=True, slots=True)
class _ItemKey:
    category: str
    scope: str
    identifier: str


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
        return f"{self._label} {self._count}"

    @property
    def category_key(self) -> str:
        return self._key

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(_CategoryClicked(self._key))


class _CategoryClicked(events.Event):
    def __init__(self, category_key: str) -> None:
        super().__init__()
        self.category_key = category_key


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


class _ScopeClicked(events.Event):
    def __init__(self, scope: str) -> None:
        super().__init__()
        self.scope = scope


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
        height: 3;
        width: 100%;
        padding: 0;
    }}
    #se-editor-dialog #se-editor-llm-prompt {{
        width: 1fr;
    }}
    #se-editor-dialog #se-editor-generate {{
        margin: 0 0 0 1;
        height: 3;
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
        provider=None,
        model: str = "",
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
        self._provider = provider
        self._model = model
        self._generating = False

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
            if self._creating and self._provider is not None:
                with Horizontal(classes="se-prompt-row"):
                    yield Input(
                        placeholder=self._llm_placeholder(),
                        id="se-editor-llm-prompt",
                    )
                    yield Button("◆ Generate", id="se-editor-generate")
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

    def _llm_placeholder(self) -> str:
        return {
            "agents": "describe the agent's job — eg. 'reviews TypeScript PRs for type safety'",
            "skills": "describe the skill — eg. 'recipes for migrating SQLAlchemy models'",
            "commands": "describe the command — eg. 'prints current branch and uncommitted files'",
            "tools": "describe the tool — eg. 'calls a local HTTP endpoint and returns JSON'",
            "prompts": "describe the prompt — eg. 'explains a Python traceback'",
            "mcp": "describe the MCP server — eg. 'wraps the github CLI'",
        }.get(self._category.key, "describe what you want")

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

    # ── LLM-assisted generation ─────────────────────────────────

    def _start_llm_generation(self) -> None:
        if self._generating:
            return
        if self._provider is None or not self._model:
            self._flash_subheader("LLM not configured — type body manually.")
            return
        try:
            prompt_input = self.query_one("#se-editor-llm-prompt", Input)
        except Exception:
            return
        user_brief = prompt_input.value.strip()
        if not user_brief:
            self._flash_subheader("Type a one-line brief, then click Generate.")
            return
        self._generating = True
        try:
            btn = self.query_one("#se-editor-generate", Button)
            btn.label = "◆ Generating…"
            btn.add_class("-busy")
        except Exception:
            pass
        self._generate_worker(user_brief)

    def _flash_subheader(self, text: str) -> None:
        try:
            self.query_one(".se-editor-subheader", Static).update(f"  {text}")
        except Exception:
            pass

    @work(exclusive=True, group="self_edit_modal_generate")
    async def _generate_worker(self, user_brief: str) -> None:
        prompt = _build_generation_prompt(self._category.key, user_brief)
        body = ""
        try:
            from taui.agent.types import Message

            messages = [Message(role="user", content=prompt)]
            async for event in self._provider.stream_text(
                messages, self._model, temperature=0.2
            ):
                if event.type == "text_delta" and event.delta:
                    body += event.delta
            body = _strip_code_fence(body).strip() + "\n"
        except Exception as exc:
            self._flash_subheader(f"LLM error: {exc}")
            self._generating = False
            try:
                btn = self.query_one("#se-editor-generate", Button)
                btn.label = "◆ Generate"
                btn.remove_class("-busy")
            except Exception:
                pass
            return

        try:
            area = self.query_one("#se-editor-body", TextArea)
            area.text = body
            area.focus()
            self._flash_subheader("Generated. Edit if needed, then Ctrl+S to save.")
        except Exception:
            pass
        finally:
            self._generating = False
            try:
                btn = self.query_one("#se-editor-generate", Button)
                btn.label = "◆ Generate"
                btn.remove_class("-busy")
            except Exception:
                pass


def _build_generation_prompt(category_key: str, user_brief: str) -> str:
    """Per-category prompt template that gets sent to the LLM."""
    common = (
        "Output ONLY the file body, no surrounding explanation, no code fences. "
        "Be concise. Use the exact format described."
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
    #se-title-row {{
        height: 1;
        background: {PANEL_BG};
        color: {ACCENT};
        padding: 0 2;
    }}
    #se-tabs-row {{
        height: 1;
        background: {PANEL_BG};
        padding: 0 2;
    }}
    #se-tabs-row _CategoryTab {{
        margin: 0 1 0 0;
    }}
    #se-scope-row {{
        height: 1;
        background: {PANEL_BG};
        padding: 0 2;
        color: {ACCENT_SOFT};
    }}
    #se-scope-row _ScopeChip {{
        margin: 0 1 0 0;
    }}
    #se-description {{
        height: 2;
        color: #8a8a8a;
        padding: 0 2;
    }}
    #se-body {{
        height: 1fr;
        background: {PANEL_BG};
        padding: 0 1;
    }}
    #se-list-pane {{
        width: 40%;
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
    #se-preview-pane {{
        width: 1fr;
        height: 1fr;
        padding: 0 0 0 1;
    }}
    #se-preview-pane .se-preview-header {{
        height: 1;
        color: {ACCENT_SOFT};
        text-style: bold;
        background: {PANEL_BG};
    }}
    #se-preview-pane #se-preview {{
        height: 1fr;
        width: 100%;
        background: {INNER_BG};
        color: #b8b8b8;
        border: solid {GRID_GREY};
        padding: 1;
    }}
    #se-footer {{
        height: 1;
        background: {PANEL_BG};
        color: {ACCENT_SOFT};
        padding: 0 2;
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
            yield Static("▰  self · edit", id="se-title-row")
            with Horizontal(id="se-tabs-row"):
                counts = inventory.counts(self._working_dir)
                for i, cat in enumerate(inventory.CATEGORIES):
                    yield _CategoryTab(
                        cat.key,
                        cat.label,
                        counts.get(cat.key, {}).get(self._scope, 0),
                        active=(i == self._category_index),
                    )
            with Horizontal(id="se-scope-row"):
                yield Static("scope", classes="se-scope-label")
                yield _ScopeChip("global", active=self._scope == "global")
                yield _ScopeChip("project", active=self._scope == "project")
                yield Static(
                    f"  {inventory.scope_root(self._working_dir, self._scope)}",
                    id="se-scope-path",
                )
            yield Static(self._category.description, id="se-description")
            with Horizontal(id="se-body"):
                with Vertical(id="se-list-pane"):
                    yield OptionList(id="se-options")
                with Vertical(id="se-preview-pane"):
                    yield Static(
                        "preview",
                        classes="se-preview-header",
                    )
                    yield Static("", id="se-preview", markup=False)
            yield Static(
                "n new · e edit · d delete · ←→ category · tab scope · esc close",
                id="se-footer",
            )

    def on_mount(self) -> None:
        self._refresh_items()
        try:
            self.query_one("#se-options", OptionList).focus()
        except Exception:
            pass

    # ── Refresh ───────────────────────────────────────────────────

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
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        counts = inventory.counts(self._working_dir)
        try:
            tabs_row = self.query_one("#se-tabs-row", Horizontal)
        except Exception:
            tabs_row = None
        if tabs_row is not None:
            for i, tab in enumerate(tabs_row.query(_CategoryTab)):
                cat = inventory.CATEGORIES[i]
                tab._count = counts.get(cat.key, {}).get(self._scope, 0)
                if i == self._category_index:
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
                f"  {inventory.scope_root(self._working_dir, self._scope)}"
            )
        except Exception:
            pass
        try:
            self.query_one("#se-description", Static).update(
                self._category.description
            )
        except Exception:
            pass

    def _render_item_row(self, item: inventory.Item) -> Text:
        text = Text()
        marker = "■" if item.builtin else "▸"
        text.append(f" {marker} ", style=ACCENT)
        text.append(f"{item.label:<24s}", style=f"bold {ACCENT}")
        suffix = " [builtin]" if item.builtin else ""
        text.append(f" {item.summary}{suffix}", style="#cccccc")
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
        provider, model = self._llm_handles()
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=True,
            item=None,
            provider=provider,
            model=model,
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
            except Exception as exc:
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
        provider, model = self._llm_handles()
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=False,
            item=item,
            provider=provider,
            model=model,
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
            except Exception as exc:
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
            except Exception as exc:
                self.app.bell()
                self._toast(f"Delete failed: {exc}")
                return
            self._refresh_items()

        self.app.push_screen(confirm, after)

    def _toast(self, message: str) -> None:
        try:
            self.query_one("#se-description", Static).update(
                f"[bold {HAZARD_AMBER}]{message}[/bold {HAZARD_AMBER}]"
            )
        except Exception:
            pass

    def _llm_handles(self):
        """Return (provider, model) from the current session, or (None, '')."""
        session = getattr(self.app, "_session", None)
        if session is None:
            return None, ""
        provider = getattr(session, "_provider", None)
        config = getattr(session, "config", None)
        model = ""
        if config is not None:
            model = str(getattr(config, "model", "") or "")
        return provider, model

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
