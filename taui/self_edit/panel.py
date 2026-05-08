"""Pinned self-edit inventory panel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Collapsible, Select, Static

from taui.extensions import ExtensionRegistry
from taui.self_edit.scaffolding import find_tool_source
from taui.self_edit.store import AgentProfile, ExtensionSource, SelfEditStore, ToolSource
from taui.skills import SkillRegistry


@dataclass(slots=True)
class _Row:
    kind: str
    name: str
    label: str


class SelectableRow(Static, can_focus=True):
    """Single focusable inventory row."""

    DEFAULT_CSS = """
    SelectableRow {
        height: 1;
        width: 100%;
        padding: 0 1;
        color: $text;
        overflow-x: hidden;
    }
    SelectableRow:hover {
        background: $surface-lighten-1;
    }
    SelectableRow:focus {
        background: #586069 20%;
        color: $text;
    }
    SelectableRow.is-selected {
        background: #586069 30%;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("enter", "select_row", "Select", show=False),
        Binding("space", "select_row", "Select", show=False),
    ]

    def __init__(self, row: _Row) -> None:
        super().__init__(row.label, markup=False)
        self._row = row

    @property
    def kind(self) -> str:
        return self._row.kind

    @property
    def name(self) -> str:
        return self._row.name

    def action_select_row(self) -> None:
        self.post_message(SelfEditPanel.RowSelected(self._row.kind, self._row.name))

    def on_click(self, event: Click) -> None:
        event.stop()
        self.focus()
        self.post_message(SelfEditPanel.RowSelected(self._row.kind, self._row.name))


class SelfEditPanel(Widget):
    """Pinned inventory panel for self-edit mode."""

    DEFAULT_CSS = """
    SelfEditPanel {
        width: 100%;
        height: auto;
        max-height: 60%;
        background: $surface;
        border: tall #7a6410;
        margin: 1 2 1 2;
        padding: 0 1;
        overflow-y: auto;
        overflow-x: hidden;
        scrollbar-size: 1 1;
    }
    SelfEditPanel Collapsible {
        width: 100%;
        height: auto;
        background: transparent;
        border: none;
        margin: 0 0 1 0;
        padding: 0;
    }
    SelfEditPanel CollapsibleTitle {
        height: 1;
        background: transparent;
        color: $text-muted;
        padding: 0 1;
    }
    SelfEditPanel Contents {
        width: 100%;
        height: auto;
        padding: 0 1 0 1;
        overflow-x: hidden;
    }
    SelfEditPanel .se-rows {
        width: 100%;
        height: auto;
        overflow-x: hidden;
    }
    SelfEditPanel #self-edit-panel-heading {
        height: 1;
        color: #f0c808;
        text-style: bold;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    SelfEditPanel #self-edit-scope-select {
        width: 24;
        height: 3;
        margin: 0 0 1 0;
    }
    SelfEditPanel #self-edit-scope-row {
        width: auto;
        height: 3;
        margin: 0 1 0 1;
        align-horizontal: left;
    }
    SelfEditPanel #self-edit-scope-label {
        width: auto;
        height: 1;
        margin: 1 1 0 0;
        color: $text-muted;
    }
    SelfEditPanel #self-edit-panel-footer {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    class RowSelected(Message):
        def __init__(self, kind: str, name: str) -> None:
            super().__init__()
            self.kind = kind
            self.name = name

    class ScopeChanged(Message):
        def __init__(self, scope: str) -> None:
            super().__init__()
            self.scope = scope

    selected_kind: reactive[str | None] = reactive(None)
    selected_name: reactive[str | None] = reactive(None)
    scope: reactive[str] = reactive("project")
    playbook: reactive[str | None] = reactive(None)

    def __init__(
        self,
        *,
        working_dir: Path,
        store: SelfEditStore,
        builtin_tool_names: set[str],
        registry,
        ext_registry: ExtensionRegistry | None = None,
        id: str = "self-edit-panel",
    ) -> None:
        super().__init__(id=id)
        self._working_dir = working_dir
        self._store = store
        self._builtin_tool_names = builtin_tool_names
        self._registry = registry
        self._ext_registry = ext_registry
        self._counts: dict[str, int] = {
            "agent": 0,
            "tool": 0,
            "extension": 0,
            "skill": 0,
        }

    def compose(self) -> ComposeResult:
        yield Static("self-edit ////////////", id="self-edit-panel-heading", markup=False)
        with Horizontal(id="self-edit-scope-row"):
            yield Static("scope:", id="self-edit-scope-label", markup=False)
            yield Select[str](
                (("global", "global"), ("project", "project")),
                prompt="scope",
                allow_blank=False,
                value=self.scope,
                id="self-edit-scope-select",
                compact=True,
            )
        with Collapsible(title="Agents (0)", id="se-section-agent", collapsed=False):
            yield Vertical(id="se-rows-agent", classes="se-rows")
        with Collapsible(title="Tools (0)", id="se-section-tool"):
            yield Vertical(id="se-rows-tool", classes="se-rows")
        with Collapsible(title="Extensions (0)", id="se-section-extension"):
            yield Vertical(id="se-rows-extension", classes="se-rows")
        with Collapsible(title="Skills (0)", id="se-section-skill"):
            yield Vertical(id="se-rows-skill", classes="se-rows")
        yield Static("", id="self-edit-panel-footer", markup=True)

    def on_mount(self) -> None:
        self.refresh_inventory()
        self._update_footer()

    # ── Public API ────────────────────────────────────────────────────

    def refresh_inventory(self) -> None:
        """Re-scan inventory and rebuild rows."""
        agents = self._store.load_agents()
        tools = self._discover_tools()
        extensions = self._discover_extensions()
        skills = self._discover_skills()

        self._render_section(
            "agent",
            [self._agent_row(a) for a in sorted(agents.values(), key=lambda x: x.id)],
        )
        self._render_section(
            "tool",
            [self._tool_row(name, tools.get(name)) for name in self._registry.names],
        )
        self._render_section(
            "extension",
            [self._extension_row(ext) for _, ext in sorted(extensions.items())],
        )
        self._render_section(
            "skill",
            [self._skill_row(skill) for skill in skills],
        )
        self._update_section_titles()

        # Drop selection if it no longer exists.
        if self.selected_kind and self.selected_name:
            kind = self.selected_kind
            name = self.selected_name
            present = self._row_exists(kind, name)
            if not present:
                self.selected_kind = None
                self.selected_name = None
        self._update_footer()
        self._refresh_selection_styles()

    def set_selection(self, kind: str | None, name: str | None) -> None:
        self.selected_kind = kind
        self.selected_name = name
        self._refresh_selection_styles()
        self._update_footer()

    def set_scope(self, scope: str) -> None:
        self.scope = scope
        try:
            scope_select = self.query_one("#self-edit-scope-select", Select)
        except Exception:
            pass
        else:
            if scope_select.value != scope:
                scope_select.value = scope
        self._update_footer()

    def set_playbook(self, playbook: str | None) -> None:
        self.playbook = playbook
        self._update_footer()

    @on(RowSelected)
    def _handle_row_selected(self, event: RowSelected) -> None:
        # Update local selection state and re-style; bubble up to the app.
        self.set_selection(event.kind, event.name)

    @on(Select.Changed, "#self-edit-scope-select")
    def _handle_scope_changed(self, event: Select.Changed) -> None:
        if event.value not in ("global", "project"):
            return
        if self.scope != event.value:
            self.scope = event.value
            self._update_footer()
            self.post_message(SelfEditPanel.ScopeChanged(event.value))

    @on(Collapsible.Expanded)
    def _handle_section_expanded(self, event: Collapsible.Expanded) -> None:
        """Keep self-edit sections in accordion mode."""
        for section in self.query(Collapsible):
            if section is not event.collapsible:
                section.collapsed = True

    # ── Discovery ─────────────────────────────────────────────────────

    def _discover_tools(self) -> dict[str, ToolSource]:
        extension_paths = self._extension_paths()
        sources: dict[str, ToolSource] = {}
        for name in self._registry.names:
            sources[name] = ToolSource(
                name=name,
                path=(
                    None
                    if name in self._builtin_tool_names
                    else find_tool_source(name, extension_paths)
                ),
            )
        return sources

    def _extension_paths(self) -> list[Path]:
        paths: list[Path] = []
        for base in (
            Path.home() / ".taui" / "extensions",
            self._working_dir / ".taui" / "extensions",
        ):
            if base.is_dir():
                paths.extend(sorted(base.glob("*.py")))
        return paths

    def _discover_extensions(self) -> dict[str, ExtensionSource]:
        registry = ExtensionRegistry(self._working_dir, include_builtins=True)
        registry.discover()
        if self._ext_registry is not None:
            for session_ext in self._ext_registry.list_all():
                ext = registry.get(session_ext.name)
                if ext is None:
                    continue
                ext.loaded = session_ext.loaded
                ext.error = session_ext.error
        return {
            ext.name: ExtensionSource(
                name=ext.name,
                path=ext.path,
                scope=ext.scope,
                description=ext.description,
                loaded=ext.loaded,
                error=ext.error,
            )
            for ext in registry.list_all()
        }

    def _discover_skills(self):
        registry = SkillRegistry(self._working_dir)
        registry.discover()
        return registry.list_all()

    # ── Row rendering ─────────────────────────────────────────────────

    def _agent_row(self, profile: AgentProfile) -> _Row:
        model = " / ".join(x for x in (profile.provider, profile.model) if x) or "inherit"
        prompt = str(profile.prompt_path) if profile.prompt_path else "(inline)"
        prompt = self._shorten(prompt)
        label = f"  {profile.id:<4} {profile.name[:18]:<18} {model[:14]:<14} {prompt}"
        return _Row(kind="agent", name=profile.id, label=label)

    def _tool_row(self, name: str, source: ToolSource | None) -> _Row:
        tool = self._registry.get(name)
        category = tool.category.value if tool else ""
        path = "built-in" if name in self._builtin_tool_names else (
            self._shorten(str(source.path)) if source and source.path else "(unknown)"
        )
        label = f"  {name[:24]:<24} {category[:12]:<12} {path}"
        return _Row(kind="tool", name=name, label=label)

    def _extension_row(self, ext: ExtensionSource) -> _Row:
        status = "error" if ext.error else ("loaded" if ext.loaded else "off")
        path = self._shorten(str(ext.path)) if ext.path else "built-in"
        label = f"  {ext.name[:20]:<20} {ext.scope[:8]:<8} {status[:8]:<8} {path}"
        return _Row(kind="extension", name=ext.name, label=label)

    def _skill_row(self, skill) -> _Row:
        path = self._shorten(str(skill.path))
        label = f"  {skill.name[:24]:<24} {skill.scope[:8]:<8} {path}"
        return _Row(kind="skill", name=skill.name, label=label)

    def _shorten(self, value: str, limit: int = 60) -> str:
        try:
            wd = str(self._working_dir)
            if value.startswith(wd):
                value = "." + value[len(wd):]
        except Exception:
            pass
        if len(value) <= limit:
            return value
        return "…" + value[-(limit - 1):]

    def _render_section(self, kind: str, rows: list[_Row]) -> None:
        try:
            container = self.query_one(f"#se-rows-{kind}", Vertical)
        except Exception:
            return
        # Remove existing children (sync)
        for child in list(container.children):
            child.remove()
        for row in rows:
            container.mount(SelectableRow(row))
        self._counts[kind] = len(rows)

    def _update_section_titles(self) -> None:
        for kind, label in (
            ("agent", "Agents"),
            ("tool", "Tools"),
            ("extension", "Extensions"),
            ("skill", "Skills"),
        ):
            try:
                section = self.query_one(f"#se-section-{kind}", Collapsible)
            except Exception:
                continue
            section.title = f"{label} ({self._counts[kind]})"

    def _row_exists(self, kind: str, name: str) -> bool:
        try:
            container = self.query_one(f"#se-rows-{kind}", Vertical)
        except Exception:
            return False
        for child in container.children:
            if isinstance(child, SelectableRow) and child.name == name:
                return True
        return False

    def _refresh_selection_styles(self) -> None:
        for row in self.query(SelectableRow):
            if (
                self.selected_kind == row.kind
                and self.selected_name == row.name
            ):
                row.add_class("is-selected")
            else:
                row.remove_class("is-selected")

    def _update_footer(self) -> None:
        try:
            footer = self.query_one("#self-edit-panel-footer", Static)
        except Exception:
            return
        if self.selected_kind and self.selected_name:
            sel = f"selection: {self.selected_kind} {self.selected_name}"
        else:
            sel = "selection: -"
        footer.update(f"[dim]{escape(sel)}[/dim]")
