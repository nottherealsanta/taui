"""Configuration screen — the new self-edit mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Select, Static

from taui.config import Config
from taui.self_edit.store import AgentProfile, SelfEditStore
from taui.tools.registry import ToolRegistry


@dataclass
class _PendingChanges:
    """Track what has been modified since last save."""

    agents: dict[str, AgentProfile]  # agent_id -> modified profile
    deleted_agents: set[str]
    tool_policies: dict[str, str]  # tool_name -> policy
    config_fields: dict[str, Any]  # field_name -> new value
    system_prompt_template: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(
            self.agents
            or self.deleted_agents
            or self.tool_policies
            or self.config_fields
            or self.system_prompt_template is not None
        )


class ConfigScreen(ModalScreen[bool]):
    """Full-screen configuration panel.

    Dismisses with True if changes were applied, False otherwise.
    """

    class SaveRequested(Message):
        """Fired when the user saves config."""

    class AgentActivated(Message):
        """Fired when user activates an agent profile."""

        def __init__(self, profile: AgentProfile) -> None:
            super().__init__()
            self.profile = profile

    DEFAULT_CSS = """
    ConfigScreen {
        background: $surface-darken-1;
    }
    #config-root {
        width: 100%;
        height: 100%;
    }
    #config-header {
        height: 3;
        background: $surface;
        border-bottom: solid $surface-lighten-1;
        padding: 0 2;
    }
    #config-header-title {
        width: 1fr;
        padding: 1 0;
        text-style: bold;
        color: #f0c674;
    }
    #scope-area {
        width: auto;
        height: 3;
        padding: 0 1;
    }
    #config-body {
        height: 1fr;
    }
    #config-sidebar {
        width: 24;
        background: $surface;
        border-right: solid $surface-lighten-1;
        padding: 1 0;
    }
    #config-sidebar ListView {
        height: auto;
    }
    #config-sidebar ListItem {
        padding: 0 2;
    }
    #config-sidebar ListItem.--highlight {
        background: $accent;
    }
    .sidebar-heading {
        color: $text-muted;
        text-style: bold;
        padding: 1 2 0 2;
    }
    #config-detail {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
    }
    #config-footer {
        height: 1;
        background: $surface;
        border-top: solid $surface-lighten-1;
        padding: 0 2;
        color: $text-muted;
    }
    .detail-placeholder {
        color: $text-muted;
        padding: 2;
    }
    """

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "close", "Close"),
    ]

    def __init__(
        self,
        config: Config,
        store: SelfEditStore,
        registry: ToolRegistry,
        *,
        current_agent_id: str = "",
    ) -> None:
        super().__init__()
        self._config = config
        self._store = store
        self._registry = registry
        self._current_agent_id = current_agent_id

        self._scope = store.load_default_scope()
        self._agents: dict[str, AgentProfile] = {}
        self._pending = _PendingChanges(
            agents={},
            deleted_agents=set(),
            tool_policies={},
            config_fields={},
        )
        self._activated_profile: AgentProfile | None = None
        self._saved = False
        self._current_section: str = "agents"
        self._current_item: str | None = None

    @property
    def activated_profile(self) -> AgentProfile | None:
        return self._activated_profile

    def compose(self) -> ComposeResult:
        with Vertical(id="config-root"):
            with Horizontal(id="config-header"):
                yield Static("TAUI Config", id="config-header-title")
                with Horizontal(id="scope-area"):
                    yield Label("scope: ")
                    yield Select(
                        [("project", "project"), ("global", "global")],
                        value=self._scope,
                        id="scope-select",
                        allow_blank=False,
                    )
            with Horizontal(id="config-body"):
                with Vertical(id="config-sidebar"):
                    yield Static("AGENTS", classes="sidebar-heading")
                    yield ListView(id="agent-list")
                    yield Static("TOOLS", classes="sidebar-heading")
                    yield ListView(id="tool-list")
                    yield Static("GENERAL", classes="sidebar-heading")
                    yield ListView(
                        ListItem(Label("Settings"), id="item-general"),
                        id="general-list",
                    )
                with VerticalScroll(id="config-detail"):
                    yield Static(
                        "Select an item from the sidebar.",
                        classes="detail-placeholder",
                    )
            yield Static(
                "Ctrl+S save  │  Esc close  │  Tab navigate",
                id="config-footer",
            )

    async def on_mount(self) -> None:
        self._agents = self._store.load_agents()
        await self._rebuild_sidebar()
        # Auto-select current agent if known
        if self._current_agent_id and self._current_agent_id in self._agents:
            self._current_section = "agents"
            self._current_item = self._current_agent_id
            await self._show_agent_editor(self._current_agent_id)

    async def _rebuild_sidebar(self) -> None:
        """Rebuild sidebar lists from current data."""
        agent_list = self.query_one("#agent-list", ListView)
        await agent_list.clear()
        for profile in sorted(self._agents.values(), key=lambda a: a.id):
            marker = " ●" if profile.id == self._current_agent_id else ""
            item = ListItem(
                Label(f"{profile.id}  {profile.name}{marker}"),
                id=f"agent-{profile.id}",
            )
            await agent_list.append(item)
        # "+ New Agent" item
        await agent_list.append(ListItem(Label("[dim]+ New Agent[/dim]"), id="agent-NEW"))

        tool_list = self.query_one("#tool-list", ListView)
        await tool_list.clear()
        for name in self._registry.names:
            await tool_list.append(ListItem(Label(name), id=f"tool-{name}"))

    @on(Select.Changed, "#scope-select")
    def _on_scope_changed(self, event: Select.Changed) -> None:
        self._scope = str(event.value)
        self._store.save_default_scope(self._scope)
        self._agents = self._store.load_agents()
        self.call_after_refresh(self._rebuild_sidebar)

    @on(ListView.Selected, "#agent-list")
    async def _on_agent_selected(self, event: ListView.Selected) -> None:
        item_id = str(event.item.id or "")
        if item_id == "agent-NEW":
            await self._create_new_agent()
            return
        agent_id = item_id.removeprefix("agent-")
        if agent_id in self._agents:
            self._current_section = "agents"
            self._current_item = agent_id
            await self._show_agent_editor(agent_id)

    @on(ListView.Selected, "#tool-list")
    async def _on_tool_selected(self, event: ListView.Selected) -> None:
        item_id = str(event.item.id or "")
        tool_name = item_id.removeprefix("tool-")
        if tool_name in self._registry:
            self._current_section = "tools"
            self._current_item = tool_name
            await self._show_tool_editor(tool_name)

    @on(ListView.Selected, "#general-list")
    async def _on_general_selected(self, event: ListView.Selected) -> None:
        self._current_section = "general"
        self._current_item = "settings"
        await self._show_general_editor()

    async def _show_agent_editor(self, agent_id: str) -> None:
        from taui.self_edit.agent_editor import AgentEditor

        profile = self._pending.agents.get(agent_id) or self._agents.get(agent_id)
        if profile is None:
            return
        detail = self.query_one("#config-detail", VerticalScroll)
        await detail.remove_children()
        editor = AgentEditor(
            profile,
            all_tool_names=self._registry.names,
            is_active=profile.id == self._current_agent_id,
        )
        await detail.mount(editor)

    async def _show_tool_editor(self, tool_name: str) -> None:
        from taui.self_edit.tool_editor import ToolEditor

        try:
            tool = self._registry.get(tool_name)
        except ValueError:
            return
        detail = self.query_one("#config-detail", VerticalScroll)
        await detail.remove_children()
        editor = ToolEditor(tool)
        await detail.mount(editor)

    async def _show_general_editor(self) -> None:
        from taui.self_edit.general_editor import GeneralEditor

        detail = self.query_one("#config-detail", VerticalScroll)
        await detail.remove_children()
        editor = GeneralEditor(self._config)
        await detail.mount(editor)

    async def _create_new_agent(self) -> None:
        """Create a new agent profile with a generated ID."""
        import string

        existing_ids = set(self._agents.keys())
        # Generate a unique 3-letter ID
        new_id: str | None = None
        for c1 in string.ascii_uppercase:
            for c2 in string.ascii_uppercase:
                for c3 in string.ascii_uppercase:
                    candidate = f"{c1}{c2}{c3}"
                    if candidate not in existing_ids:
                        new_id = candidate
                        break
                else:
                    continue
                break
            else:
                continue
            break

        if new_id is None:
            self.notify("No available agent IDs", severity="error")
            return

        profile = AgentProfile(
            id=new_id,
            name="New Agent",
            prompt="You are a helpful assistant.",
            provider="",
            model="",
            allowed_tools=[],
            tool_config={},
        )
        self._agents[new_id] = profile
        self._pending.agents[new_id] = profile
        await self._rebuild_sidebar()
        self._current_section = "agents"
        self._current_item = new_id
        await self._show_agent_editor(new_id)

    @on(AgentActivated)
    def _on_agent_activated(self, event: AgentActivated) -> None:
        self._activated_profile = event.profile
        self.notify(
            f"Agent {event.profile.id} will be activated on close",
            severity="information",
        )

    # ── Save / Close ─────────────────────────────────────────────────

    def _collect_pending_from_editors(self) -> None:
        """Collect changes from currently mounted editors."""
        from taui.self_edit.agent_editor import AgentEditor
        from taui.self_edit.general_editor import GeneralEditor

        try:
            editor = self.query_one(AgentEditor)
            profile = editor.collect()
            if profile:
                self._pending.agents[profile.id] = profile
        except Exception:
            pass

        try:
            editor = self.query_one(GeneralEditor)
            changes = editor.collect()
            if changes:
                self._pending.config_fields.update(changes)
        except Exception:
            pass

    async def action_save(self) -> None:
        """Persist all pending changes."""
        self._collect_pending_from_editors()
        if not self._pending.has_changes:
            self.notify("No changes to save", severity="information")
            return

        # Save agents
        for agent_id, profile in self._pending.agents.items():
            self._agents[agent_id] = profile
            self._store.save_agent(profile, self._scope)

        # Delete agents
        for agent_id in self._pending.deleted_agents:
            self._agents.pop(agent_id, None)
            # Delete prompt file
            prompt_path = self._store._agent_prompt_file(self._scope, agent_id)
            if prompt_path.exists():
                prompt_path.unlink()

        # Apply config changes
        for key, value in self._pending.config_fields.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

        # Reset pending
        self._pending = _PendingChanges(
            agents={},
            deleted_agents=set(),
            tool_policies={},
            config_fields={},
        )
        self._saved = True
        self.notify("Config saved", severity="information")
        await self._rebuild_sidebar()

    async def action_close(self) -> None:
        """Close the config screen."""
        self._collect_pending_from_editors()
        if self._pending.has_changes:
            # Show confirmation
            self.notify(
                "Unsaved changes — press Esc again to discard",
                severity="warning",
            )
            # Set a flag so next Esc actually closes
            self._pending = _PendingChanges(
                agents={},
                deleted_agents=set(),
                tool_policies={},
                config_fields={},
            )
            return
        self.dismiss(self._saved)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.call_after_refresh(self.action_close)
