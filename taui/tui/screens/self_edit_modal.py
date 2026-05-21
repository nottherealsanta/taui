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
from textual.containers import Container, Grid, Horizontal, Vertical
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
    """Single clickable tool name with on/off state."""

    DEFAULT_CSS = f"""
    _ToolToggle {{
        height: 1;
        width: 1fr;
        padding: 0 1;
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

    def __init__(self, tool_name: str, selected: bool) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._selected = selected
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

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def is_selected(self) -> bool:
        return self._selected


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
        height: 8;
        width: 100%;
        border: solid {GRID_GREY};
        background: {INNER_BG};
        grid-size: 4;
        grid-rows: 1;
        grid-gutter: 0 1;
        padding: 1;
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
            yield Static("ALLOWED TOOLS  [dim](pick at least one)[/dim]",
                         classes="se-tools-label", markup=True)
            selected = set(self._initial_extra.get("allowed_tools", []))
            all_tools = inventory.all_tool_names(self._working_dir)
            with Grid(id="se-editor-tools"):
                for name in all_tools:
                    yield _ToolToggle(name, name in selected)

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
                "commands": "describe the command — eg. 'prints current branch and uncommitted files'",
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
            if not allowed_tools:
                self._flash_subheader(
                    "An agent needs at least one allowed tool — pick one below."
                )
                return
            try:
                provider_str, model_str = _split_model_id(
                    self.query_one("#se-editor-model-id", Input).value.strip()
                )
            except Exception:
                provider_str, model_str = "", ""
            extra = {
                "name": ident,
                "provider": provider_str,
                "model": model_str,
                "allowed_tools": allowed_tools,
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
    #se-list-pane #se-new-button {{
        margin-top: 1;
        height: 1;
        width: 100%;
        min-width: 0;
        border: none;
        padding: 0 1;
        background: {ACCENT};
        color: {DEEP_BLACK};
        text-style: bold;
    }}
    #se-list-pane #se-new-button:hover {{
        background: {HAZARD_AMBER};
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
            yield Static(self._category.description, id="se-description")
            with Horizontal(id="se-body"):
                with Vertical(id="se-list-pane"):
                    yield OptionList(id="se-options")
                    yield Button("+  NEW", id="se-new-button")
                with Vertical(id="se-preview-pane"):
                    yield Static("", id="se-preview", markup=False)
            yield Static(
                "n new · e edit · d delete · ←→ category · tab scope · esc close",
                id="se-footer",
            )

    def on_mount(self) -> None:
        self._layout_tabs()
        self._refresh_items()
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
        self._items = inventory.list_items(
            self._working_dir, self._category.key, self._scope
        )
        try:
            opts = self.query_one("#se-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        if not self._items:
            empty_msg = (
                "(settings are global — switch to GLOBAL scope)"
                if self._category.key == "general"
                else "(empty — press 'n' to create one)"
            )
            opts.add_option(
                Option(
                    Text(empty_msg, style=f"italic {GRID_GREY}"),
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
            self.query_one("#se-description", Static).update(
                self._category.description
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

    @on(Button.Pressed, "#se-new-button")
    def _on_new_button(self, _: Button.Pressed) -> None:
        self.action_new_item()

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
        if self._category.key == "general":
            return
        provider, model, provider_name = self._llm_handles()
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=True,
            item=None,
            working_dir=self._working_dir,
            provider=provider,
            model=model,
            provider_name=provider_name,
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
        if self._category.key == "general":
            def after_prefix(new_value: str | None) -> None:
                if new_value is None:
                    return
                try:
                    from taui.self_edit.inventory import _save_prefix_setting
                    _save_prefix_setting(item.identifier, new_value)
                except Exception as exc:
                    self.app.bell()
                    self._toast(f"Save failed: {exc}")
                    return
                self._refresh_items()

            self.app.push_screen(
                _PrefixEditor(label=item.label, current_value=item.summary.strip("'")),
                after_prefix,
            )
            return
        if item.builtin and self._category.key == "tools":
            # Built-in tools are read-only — preview-only.
            return
        provider, model, provider_name = self._llm_handles()
        editor = _Editor(
            category=self._category,
            scope=self._scope,
            creating=False,
            item=item,
            working_dir=self._working_dir,
            provider=provider,
            model=model,
            provider_name=provider_name,
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
            self.query_one("#se-description", Static).update(
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
