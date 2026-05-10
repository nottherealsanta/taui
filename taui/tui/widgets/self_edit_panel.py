"""Top-docked self-edit panel."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from taui.config import Config
from taui.self_edit.store import AgentProfile, SelfEditStore
from taui.self_edit.verbs import (
    VerbParseError,
    complete_verb,
    parse_verb,
)
from taui.tools.registry import ToolRegistry


@dataclass(slots=True)
class _PendingChanges:
    """Track what has been modified since last save."""

    agents: dict[str, AgentProfile]
    deleted_agents: set[str]
    tool_policies: dict[str, str]
    config_fields: dict[str, Any]
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


@dataclass(slots=True)
class _Row:
    section: str
    key: str
    label: str
    detail: str
    expanded: bool = False


class SelfEditPanel(Widget):
    """Configuration panel controlled by local self-edit verbs."""

    DEFAULT_CSS = """
    SelfEditPanel {
        display: none;
        height: 40%;
        min-height: 12;
        background: $surface;
        margin: 0 2 1 2;
        border: tall #f0c808;
        border-top: none;
        border-left: none;
        border-right: none;
        padding: 0;
    }
    SelfEditPanel.visible {
        display: block;
    }
    #self-edit-body {
        height: 1fr;
        color: $text;
        padding: 0 1 0 2;
    }
    #self-edit-header {
        height: 1;
        background: $surface;
        padding: 0 2;
        color: #f0c808;
        text-style: bold;
    }
    #self-edit-title {
        width: auto;
    }
    #self-edit-scope-label {
        width: auto;
        margin: 0 0 0 2;
    }
    #self-edit-unsaved {
        width: 1fr;
        text-align: right;
    }
    """

    class Activated(Message):
        def __init__(self, profile: AgentProfile) -> None:
            super().__init__()
            self.profile = profile

    class ExitRequested(Message):
        pass

    class Saved(Message):
        pass

    def __init__(
        self,
        config: Config,
        store: SelfEditStore,
        registry: ToolRegistry,
        *,
        current_agent_id: str = "",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._config = config
        self._store = store
        self._registry = registry
        self._current_agent_id = current_agent_id
        self._scope = store.load_default_scope()
        self._agents: dict[str, AgentProfile] = {}
        self._skill_names: list[str] = []
        self._mcp_server_names: list[str] = []
        self._rows: list[_Row] = []
        self._cursor = 0
        self._expanded: set[tuple[str, str]] = set()
        self._pending = _PendingChanges({}, set(), {}, {})
        self._discard_on_next_exit = False
        self._show_help = False

    @property
    def has_changes(self) -> bool:
        return self._pending.has_changes

    @property
    def current_section(self) -> str:
        return self._current_row().section if self._rows else "agents"

    @property
    def current_key(self) -> str:
        return self._current_row().key if self._rows else ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="self-edit-header"):
            yield Static("SELF-EDIT", id="self-edit-title")
            yield Static(f"[dim]{self._scope}[/]", id="self-edit-scope-label", markup=True)
            yield Static("[dim]saved[/]", id="self-edit-unsaved", markup=True)
        yield Static("", id="self-edit-body", markup=True)

    async def on_mount(self) -> None:
        self.reload()

    def set_registry(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self.reload()

    def set_current_agent(self, agent_id: str) -> None:
        self._current_agent_id = agent_id
        self.refresh_render()

    def show_panel(self) -> None:
        self.add_class("visible")
        self.can_focus = True
        self.focus()
        self.reload()

    def hide_panel(self) -> None:
        self.remove_class("visible")

    def reload(self) -> None:
        self._agents = self._store.load_agents()
        self._refresh_extension_lists()
        self._rebuild_rows()
        self.refresh_render()

    def complete(self, text: str) -> list[tuple[str, str, bool]]:
        return complete_verb(text, targets=tuple(row.key for row in self._rows))

    async def run_verb(self, text: str) -> None:
        try:
            command = parse_verb(text)
        except VerbParseError as exc:
            self.notify(str(exc), severity="error")
            return

        verb = command.verb
        args = command.args
        raw_args = command.raw_args

        if verb in ("?", "help"):
            self._show_help = True
            self.refresh_render()
            return
        if verb in ("agent", "tool", "skill", "mcp"):
            self._verb_asset(verb, args, raw_args)
            return
        if verb == "exit":
            await self.request_exit()
            return
        if verb == "save":
            await self.save()
            return
        if verb == "confirm":
            await self.save()
            return
        if verb == "discard":
            self._pending = _PendingChanges({}, set(), {}, {})
            self._discard_on_next_exit = False
            self.reload()
            self.notify("Discarded pending self-edit changes", severity="information")
            return

    async def request_exit(self) -> None:
        if self._pending.has_changes and not self._discard_on_next_exit:
            self._discard_on_next_exit = True
            self.notify(
                "Unsaved changes - run exit again to discard",
                severity="warning",
            )
            return
        if self._discard_on_next_exit:
            self._pending = _PendingChanges({}, set(), {}, {})
            self._discard_on_next_exit = False
        self.post_message(self.ExitRequested())

    async def save(self) -> None:
        if not self._pending.has_changes:
            self.notify("No changes to save", severity="information")
            return
        for agent_id, profile in self._pending.agents.items():
            if agent_id in self._pending.deleted_agents:
                continue
            self._agents[agent_id] = profile
            self._store.save_agent(profile, self._scope)
        for agent_id in self._pending.deleted_agents:
            self._agents.pop(agent_id, None)
            self._store.delete_agent(agent_id, self._scope)
        for key, value in self._pending.config_fields.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self._pending = _PendingChanges({}, set(), {}, {})
        self._discard_on_next_exit = False
        self.reload()
        self.post_message(self.Saved())
        self.notify("Self-edit changes saved", severity="information")

    def _verb_asset(
        self,
        kind: str,
        args: tuple[str, ...],
        raw_args: str,
    ) -> None:
        if not args:
            self.notify(f"Usage: /{kind} new|view|edit|list|remove ...", severity="error")
            return
        action = args[0]
        action_args = args[1:]
        action_raw = raw_args[len(action) :].strip()
        if action == "list":
            self._move_to_section(f"{kind}s" if kind != "mcp" else "mcp")
            return
        if action == "view":
            self._verb_view(kind, action_args)
            return
        if kind == "agent":
            self._verb_agent_action(action, action_args, action_raw)
            return
        if kind == "tool":
            self._verb_tool_action(action, action_args, action_raw)
            return
        if kind == "skill":
            self._verb_skill_action(action, action_args, action_raw)
            return
        if kind == "mcp":
            self._verb_mcp_action(action, action_args, action_raw)

    def _verb_view(self, kind: str, args: tuple[str, ...]) -> None:
        """Navigate to and expand the specified item."""
        needle = args[0] if args else self._current_row().key
        if not needle:
            self.notify(f"Usage: /{kind} view <name>", severity="error")
            return
        needle_lower = needle.casefold()
        section = f"{kind}s" if kind != "mcp" else "mcp"
        for index, row in enumerate(self._rows):
            if row.section == section and (
                row.key.casefold() == needle_lower
                or row.label.casefold().startswith(needle_lower)
            ):
                self._cursor = index
                key = (row.key, row.section)
                self._expanded.add(key)
                self._rebuild_rows()
                self.refresh_render()
                return
        self.notify(f"No {kind} matches: {needle}", severity="error")

    def _verb_agent_action(
        self,
        action: str,
        args: tuple[str, ...],
        raw_args: str,
    ) -> None:
        if action == "new":
            description = raw_args.strip().strip('"') or "Agent"
            agent_id = self._next_agent_id()
            profile = AgentProfile(
                id=agent_id,
                name=self._title_from_text(description),
                prompt=description,
                provider="",
                model="",
                allowed_tools=[],
            )
            self._set_agent(profile, move=True)
            self.notify(f"Created agent {agent_id}; run save to persist.")
            return
        if action == "edit":
            row = self._current_row()
            agent_id = args[0].upper() if args and len(args[0]) == 3 else row.key
            text = " ".join(args) if agent_id == row.key else raw_args
            if args and agent_id == args[0].upper():
                text = raw_args[len(args[0]) :].strip()
            text = text.strip().strip('"')
            if agent_id not in self._agents or not text:
                self.notify('Usage: /agent edit [ABC] "prompt text"', severity="error")
                return
            profile = self._agent(agent_id)
            self._set_agent(replace(profile, prompt=text), move=True)
            return
        if action == "remove":
            agent_id = (args[0] if args else self._current_row().key).upper()
            if agent_id == "DEF":
                self.notify(
                    "DEF is the default agent and cannot be removed.",
                    severity="error",
                )
                return
            if agent_id not in self._agents:
                self.notify(f"Agent not found: {agent_id}", severity="error")
                return
            self._pending.deleted_agents.add(agent_id)
            self._agents.pop(agent_id, None)
            self._pending.agents.pop(agent_id, None)
            self.reload()
            self.notify(f"Removed agent {agent_id}; run save to persist.")
            return
        self.notify("Usage: /agent new|view|edit|list|remove ...", severity="error")

    def _verb_tool_action(
        self,
        action: str,
        args: tuple[str, ...],
        raw_args: str,
    ) -> None:
        if action == "new":
            name = self._object_name(raw_args or "custom tool", separator="_")
            path = self._extension_dir_for_scope() / f"{name}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._tool_template(name, raw_args), encoding="utf-8")
            self.notify(f"Created tool extension: {path}")
            self.reload()
            return
        if action == "remove":
            name = self._object_name(
                args[0] if args else self._current_row().key,
                separator="_",
            )
            path = self._extension_dir_for_scope() / f"{name}.py"
            if not path.exists():
                self.notify(f"Tool extension not found: {name}", severity="error")
                return
            path.unlink()
            self.notify(f"Removed tool extension: {path}")
            self.reload()
            return
        if action == "edit":
            self.notify("Use your editor to modify the tool extension file.")
            return
        self.notify("Usage: /tool new|view|edit|list|remove ...", severity="error")

    def _verb_skill_action(
        self,
        action: str,
        args: tuple[str, ...],
        raw_args: str,
    ) -> None:
        if action == "new":
            name = self._object_name(raw_args or "custom skill", separator="-")
            path = self._skill_dir_for_scope() / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._skill_template(raw_args or name), encoding="utf-8")
            self.notify(f"Created skill: {path}")
            self.reload()
            return
        if action == "remove":
            name = self._object_name(
                args[0] if args else self._current_row().key,
                separator="-",
            )
            path = self._skill_dir_for_scope() / name / "SKILL.md"
            if not path.exists():
                self.notify(f"Skill not found: {name}", severity="error")
                return
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass
            self.notify(f"Removed skill: {name}")
            self.reload()
            return
        self.notify("Usage: /skill new|view|edit|list|remove ...", severity="error")

    def _verb_mcp_action(
        self,
        action: str,
        args: tuple[str, ...],
        raw_args: str,
    ) -> None:
        if action == "new":
            name = self._object_name(raw_args or "mcp_server", separator="_")
            path = self._mcp_file_for_scope()
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            separator = "" if not existing or existing.endswith("\n\n") else "\n\n"
            block = f'[servers.{name}]\ncommand = ["echo", "configure"]\nenabled = false\n'
            path.write_text(existing + separator + block, encoding="utf-8")
            self.notify(f"Created MCP server block: {name}")
            self.reload()
            return
        if action == "remove":
            self.notify("MCP remove is not implemented yet.", severity="warning")
            return
        self.notify("Usage: /mcp new|view|edit|list|remove ...", severity="error")

    def _agent(self, agent_id: str) -> AgentProfile:
        profile = self._pending.agents.get(agent_id) or self._agents[agent_id]
        return replace(
            profile,
            allowed_tools=list(profile.allowed_tools),
            tool_config=dict(profile.tool_config),
        )

    def _set_agent(self, profile: AgentProfile, *, move: bool = False) -> None:
        self._pending.agents[profile.id] = profile
        self._agents[profile.id] = profile
        self._discard_on_next_exit = False
        self._rebuild_rows()
        if move:
            self._select_row("agents", profile.id)
        self.refresh_render()

    def _agent_for_rows(
        self, selected_section: str, selected_key: str
    ) -> AgentProfile | None:
        if selected_section == "agents" and selected_key in self._agents:
            return self._agent(selected_key)
        agent_id = self._current_agent_id or "DEF"
        if agent_id in self._agents:
            return self._agent(agent_id)
        return None

    def _refresh_extension_lists(self) -> None:
        try:
            from taui.skills import SkillRegistry

            skill_registry = SkillRegistry(self._config.working_dir)
            skill_registry.discover()
            self._skill_names = skill_registry.names
        except Exception:
            self._skill_names = []
        try:
            from taui.mcp import McpManager

            mcp_manager = McpManager(self._config.working_dir)
            mcp_manager.load_configs()
            self._mcp_server_names = mcp_manager.server_names
        except Exception:
            self._mcp_server_names = []

    def _rebuild_rows(self) -> None:
        selected_row = self._rows[self._cursor] if self._rows else None
        selected = selected_row.key if selected_row else ""
        selected_section = selected_row.section if selected_row else ""
        rows: list[_Row] = []
        for profile in sorted(self._agents.values(), key=lambda item: item.id):
            if profile.id in self._pending.deleted_agents:
                continue
            model = profile.model or self._config.model or "default"
            detail = (
                f"name: {escape(profile.name)}\n"
                f"provider: {escape(profile.provider or self._config.provider)}\n"
                f"model: {escape(model)}\n"
                f"prompt: {escape(str(profile.prompt_path or '<inline>'))}\n"
                f"allowed: {escape(self._allowed_tools_summary(profile))}\n"
                f"policies: {escape(self._policy_summary(profile))}"
            )
            rows.append(
                _Row(
                    "agents",
                    profile.id,
                    f"{profile.id:<5}{profile.name[:28]:<30}",
                    model[:24],
                    (profile.id, "agents") in self._expanded,
                )
            )
            if (profile.id, "agents") in self._expanded:
                rows.append(_Row("agents", profile.id, detail, "", True))
        active_agent = self._agent_for_rows(selected_section, selected)
        for name in self._registry.names:
            policy = "auto"
            if active_agent and name in active_agent.tool_config:
                policy = active_agent.tool_config[name].policy
            rows.append(_Row("tools", name, f"{name[:30]:<32}", policy))
        for name in self._skill_names:
            rows.append(_Row("skills", name, f"{name[:30]:<32}", "discovered"))
        if not self._skill_names:
            rows.append(_Row("skills", "", "No skills found", ""))
        for name in self._mcp_server_names:
            rows.append(_Row("mcp", name, f"{name[:30]:<32}", "configured"))
        if not self._mcp_server_names:
            rows.append(_Row("mcp", "", "No MCP servers configured", ""))
        self._rows = rows
        if selected:
            self._select_key(selected)
        self._cursor = min(self._cursor, max(len(self._rows) - 1, 0))

    def _next_agent_id(self) -> str:
        existing = set(self._agents) | set(self._pending.agents)
        for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                for third in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    agent_id = f"{first}{second}{third}"
                    if agent_id not in existing:
                        return agent_id
        return "ZZZ"

    def _title_from_text(self, text: str) -> str:
        cleaned = " ".join(text.strip().strip('"').split())
        if not cleaned:
            return "Agent"
        return cleaned[:32].title()

    def _object_name(self, text: str, *, separator: str) -> str:
        cleaned = text.strip().strip('"').lower()
        cleaned = re.sub(r"[^a-z0-9]+", separator, cleaned).strip(separator)
        return cleaned or "custom"

    def _extension_dir_for_scope(self) -> Path:
        if self._scope == "project":
            return self._config.working_dir / ".taui" / "extensions"
        return Path.home() / ".taui" / "extensions"

    def _skill_dir_for_scope(self) -> Path:
        if self._scope == "project":
            return self._config.working_dir / ".taui" / "skills"
        return Path.home() / ".taui" / "skills"

    def _mcp_file_for_scope(self) -> Path:
        if self._scope == "project":
            return self._config.working_dir / ".taui" / "mcp.toml"
        return Path.home() / ".config" / "taui" / "mcp.toml"

    def _tool_template(self, name: str, description: str) -> str:
        class_name = "".join(part.title() for part in name.split("_")) or "CustomTool"
        schema = json.dumps({"type": "object", "properties": {}}, indent=8)
        description = description.strip().strip('"') or f"{name} tool"
        return f'''"""Taui tool extension."""

from __future__ import annotations

from taui.tools.base import ToolCategory, ToolResult


class {class_name}:
    name = "{name}"
    description = {description!r}
    category = ToolCategory.AGENT
    schema = {schema}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult.ok("TODO: implement tool behavior")


def register(ctx):
    ctx.tools.register({class_name}())
'''

    def _skill_template(self, description: str) -> str:
        title = self._title_from_text(description)
        return f"""# {title}

Use this skill when:
- {description.strip().strip('"') or "Describe when this skill applies."}

Workflow:
1. Add concrete steps here.
"""

    def _allowed_tools_summary(self, profile: AgentProfile) -> str:
        return ", ".join(profile.allowed_tools) if profile.allowed_tools else "all"

    def _policy_summary(self, profile: AgentProfile) -> str:
        if not profile.tool_config:
            return "default auto"
        return ", ".join(
            f"{name}:{config.policy}" for name, config in profile.tool_config.items()
        )

    def _current_row(self) -> _Row:
        if not self._rows:
            self._rebuild_rows()
        return self._rows[self._cursor]

    def _select_key(self, key: str) -> None:
        for index, row in enumerate(self._rows):
            if row.key == key:
                self._cursor = index
                return

    def _select_row(self, section: str, key: str) -> None:
        for index, row in enumerate(self._rows):
            if row.section == section and row.key == key:
                self._cursor = index
                return

    def _move_to_section(self, section: str) -> None:
        for index, row in enumerate(self._rows):
            if row.section == section:
                self._cursor = index
                self.refresh_render()
                return

    def refresh_render(self) -> None:
        try:
            self.query_one("#self-edit-body", Static).update(self._panel_markup())
            unsaved = (
                "[#f0c808]● unsaved[/]"
                if self._pending.has_changes
                else "[dim]saved[/]"
            )
            self.query_one("#self-edit-unsaved", Static).update(unsaved)
            self.query_one("#self-edit-scope-label", Static).update(
                f"[dim]{self._scope}[/]"
            )
        except Exception:
            pass

    def _panel_markup(self) -> str:
        lines: list[str] = []
        if self._show_help:
            lines.append("[bold #f0c808]/help[/bold #f0c808]")
            lines.extend(f"[dim]{escape(line)}[/dim]" for line in self._help_text().splitlines())
            lines.append("")

        last_section = ""
        for index, row in enumerate(self._rows):
            if row.section != last_section:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(f"[bold]{row.section.upper()}[/bold]")
                last_section = row.section
            marker = "[#f0c808]>[/#f0c808]" if index == self._cursor else " "
            label = escape(row.label)
            detail = escape(row.detail)
            if row.expanded and "\n" in row.label:
                lines.append(f"{marker} [dim]{label}[/dim]")
            else:
                lines.append(f"{marker} {label} [dim]{detail}[/dim]".rstrip())
        return "\n".join(lines)

    def _help_text(self) -> str:
        return (
            '/agent new "reviewer"  /agent view ABC  /agent edit ABC "prompt"\n'
            '/agent list  /agent remove ABC\n'
            '/tool new "describe tool"  /tool view name  /tool edit name\n'
            '/tool list  /tool remove name\n'
            '/skill new "describe skill"  /skill view name  /skill edit name\n'
            '/skill list  /skill remove name\n'
            '/mcp new "server name"  /mcp view name  /mcp edit name\n'
            '/mcp list  /mcp remove name\n'
            '/save  /confirm  /discard  /exit'
        )

    async def _on_key(self, event: Key) -> None:
        if event.key in ("up", "k"):
            event.prevent_default()
            event.stop()
            self._cursor = max(0, self._cursor - 1)
            self.refresh_render()
        elif event.key in ("down", "j"):
            event.prevent_default()
            event.stop()
            self._cursor = min(len(self._rows) - 1, self._cursor + 1)
            self.refresh_render()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            row = self._current_row()
            key = (row.key, row.section)
            if key in self._expanded:
                self._expanded.remove(key)
            else:
                self._expanded.add(key)
            self._rebuild_rows()
            self.refresh_render()
