"""Self-edit control surface for taui TUI."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.extensions import ExtensionRegistry
from taui.llm_provider.models import DEFAULT_MODELS, PREFERRED_MODELS
from taui.tools.executor import ToolExecutor
from taui.tools.registry import ToolRegistry


_AGENT_ID_RE = re.compile(r"^[A-Z]{3}$")
_AGENT_MODEL_SEP = "\x1f"


@dataclass(slots=True)
class AgentProfile:
    id: str
    name: str
    prompt: str
    provider: str
    model: str
    allowed_tools: list[str]


@dataclass(slots=True)
class NewToolRequest:
    name: str
    description: str
    category: str


@dataclass(slots=True)
class NewExtensionRequest:
    name: str


@dataclass(slots=True)
class ToolSource:
    name: str
    path: Path | None


@dataclass(slots=True)
class ExtensionSource:
    name: str
    path: Path | None
    scope: str
    description: str = ""
    loaded: bool = False
    error: str | None = None


_DEFAULT_AGENTS = [
    AgentProfile(
        id="BLD",
        name="Build",
        prompt="Implementation-focused software engineer. Make scoped changes and verify them.",
        provider="",
        model="",
        allowed_tools=[],
    ),
    AgentProfile(
        id="PLN",
        name="Plan",
        prompt=(
            "Planning-focused software engineer. Clarify requirements and "
            "produce concrete plans."
        ),
        provider="",
        model="",
        allowed_tools=[],
    ),
]


class SelfEditStore:
    """Disk persistence for self-edit artifacts."""

    PROJECT_DIR = Path(".taui/self_edit")
    GLOBAL_DIR = Path.home() / ".taui" / "self_edit"

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def dir_for_scope(self, scope: str) -> Path:
        if scope == "project":
            return self._working_dir / self.PROJECT_DIR
        return self.GLOBAL_DIR

    def _state_file(self) -> Path:
        return self._working_dir / self.PROJECT_DIR / "state.json"

    def load_default_scope(self) -> str:
        path = self._state_file()
        if not path.exists():
            return "project"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scope = data.get("scope", "project")
            return "global" if scope == "global" else "project"
        except (OSError, json.JSONDecodeError):
            return "project"

    def save_default_scope(self, scope: str) -> None:
        out = self._state_file()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"scope": scope}, indent=2), encoding="utf-8")

    def _agents_file(self, scope: str) -> Path:
        return self.dir_for_scope(scope) / "agents.json"

    def load_agents(self) -> dict[str, AgentProfile]:
        merged = {a.id: a for a in _DEFAULT_AGENTS}
        for scope in ("global", "project"):
            path = self._agents_file(scope)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for row in data.get("profiles", []):
                profile = _agent_from_row(row)
                if profile is not None:
                    merged[profile.id] = profile
        return merged

    def save_agent(self, profile: AgentProfile, scope: str) -> None:
        path = self._agents_file(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"profiles": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"profiles": []}

        rows = list(data.get("profiles", []))
        for index, row in enumerate(rows):
            if str(row.get("id", "")).upper() == profile.id:
                rows[index] = asdict(profile)
                break
        else:
            rows.append(asdict(profile))
        data["profiles"] = rows
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _agent_from_row(row: Any) -> AgentProfile | None:
    if not isinstance(row, dict):
        return None
    try:
        agent_id = str(row["id"]).upper()
        if not _AGENT_ID_RE.match(agent_id):
            return None
        return AgentProfile(
            id=agent_id,
            name=str(row.get("name", "")) or agent_id,
            prompt=str(row.get("prompt", "")),
            provider=str(row.get("provider", "")),
            model=str(row.get("model", "")),
            allowed_tools=[str(x) for x in row.get("allowed_tools", [])],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _scope_extension_base(working_dir: Path, scope: str) -> Path:
    if scope == "project":
        return working_dir / ".taui" / "extensions"
    return Path.home() / ".taui" / "extensions"


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return cleaned or fallback


def _unique_path(base: Path, stem: str, suffix: str) -> Path:
    path = base / f"{stem}{suffix}"
    index = 2
    while path.exists():
        path = base / f"{stem}_{index}{suffix}"
        index += 1
    return path


class NewAgentScreen(ModalScreen[AgentProfile | None]):
    """Modal form for creating an agent profile."""

    DEFAULT_CSS = """
    NewAgentScreen {
        align: center middle;
    }
    #new-agent-dialog {
        width: 88;
        height: 32;
        background: #17140a;
        border: heavy #f0c808;
        padding: 1 2;
    }
    .modal-title {
        width: 100%;
        color: #f0c808;
        text-style: bold;
        padding: 0 0 0 0;
        border-bottom: solid #5f510f;
        margin-bottom: 1;
    }
    .modal-row {
        height: auto;
        margin: 0;
    }
    .modal-label {
        width: 18;
        color: #bca849;
    }
    .modal-actions {
        height: auto;
        align: right middle;
        padding: 0;
    }
    .model-select {
        width: 1fr;
    }
    .tools-grid {
        height: auto;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1 1;
        margin: 0 0 1 0;
    }
    .tools-grid Checkbox {
        height: 3;
        padding: 0 1;
    }
    #new-agent-prompt {
        height: 7;
        scrollbar-size-vertical: 1;
    }
    NewAgentScreen Button {
        background: #2b250f;
        color: #ffe45c;
        border: tall #f0c808;
    }
    NewAgentScreen Button:hover {
        background: #f0c808;
        color: #141107;
    }
    """

    def __init__(
        self,
        *,
        default_provider: str,
        default_model: str,
        tool_names: list[str],
        existing_ids: set[str],
    ) -> None:
        super().__init__()
        self._default_provider = default_provider
        self._default_model = default_model
        self._tool_names = tool_names
        self._existing_ids = existing_ids

    def compose(self) -> ComposeResult:
        with Container(id="new-agent-dialog"):
            yield Label("[bold]NEW AGENT[/bold]", classes="modal-title")
            with Horizontal(classes="modal-row"):
                yield Label("ID", classes="modal-label")
                yield Input(placeholder="ABC", id="new-agent-id", max_length=3)
            with Horizontal(classes="modal-row"):
                yield Label("Provider / model", classes="modal-label")
                yield Select(
                    options=_agent_model_options(
                        self._default_provider,
                        self._default_model,
                        default_provider=self._default_provider,
                        default_model=self._default_model,
                    ),
                    value=_agent_model_value("", ""),
                    id="new-agent-model-profile",
                    classes="model-select",
                )
            yield Label("Allowed tools", classes="modal-label")
            yield _tools_grid(self._tool_names, set(), "new-agent-tool")
            yield Label("Prompt")
            yield TextArea(id="new-agent-prompt")
            yield Label("", id="new-agent-status")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="new-agent-cancel")
                yield Button("Create", variant="primary", id="new-agent-create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-agent-cancel":
            self.dismiss(None)
            return
        if event.button.id != "new-agent-create":
            return
        agent_id = self.query_one("#new-agent-id", Input).value.strip().upper()
        if not _AGENT_ID_RE.match(agent_id):
            self.query_one("#new-agent-status", Label).update("ID must be exactly 3 letters")
            return
        if agent_id in self._existing_ids:
            self.query_one("#new-agent-status", Label).update("ID already exists")
            return
        provider, model = _split_agent_model(
            str(self.query_one("#new-agent-model-profile", Select).value or "")
        )
        self.dismiss(
            AgentProfile(
                id=agent_id,
                name=agent_id,
                prompt=self.query_one("#new-agent-prompt", TextArea).text,
                provider=provider,
                model=model,
                allowed_tools=_selected_tools(self),
            )
        )

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class NewToolScreen(ModalScreen[NewToolRequest | None]):
    """Modal form for scaffolding a custom extension-backed tool."""

    DEFAULT_CSS = NewAgentScreen.DEFAULT_CSS.replace("NewAgentScreen", "NewToolScreen")

    def compose(self) -> ComposeResult:
        with Container(id="new-agent-dialog"):
            yield Label("[bold]NEW TOOL[/bold]", classes="modal-title")
            with Horizontal(classes="modal-row"):
                yield Label("Name", classes="modal-label")
                yield Input(placeholder="my_tool", id="new-tool-name")
            with Horizontal(classes="modal-row"):
                yield Label("Description", classes="modal-label")
                yield Input(id="new-tool-description")
            with Horizontal(classes="modal-row"):
                yield Label("Category", classes="modal-label")
                yield Select(
                    options=[
                        ("agent", "agent"),
                        ("file_read", "file_read"),
                        ("file_write", "file_write"),
                        ("search", "search"),
                        ("shell", "shell"),
                        ("git", "git"),
                        ("memory", "memory"),
                        ("question", "question"),
                    ],
                    value="agent",
                    id="new-tool-category",
                )
            yield Label("", id="new-tool-status")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="new-tool-cancel")
                yield Button("Create", variant="primary", id="new-tool-create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-tool-cancel":
            self.dismiss(None)
            return
        if event.button.id != "new-tool-create":
            return
        name = _slug(self.query_one("#new-tool-name", Input).value, "")
        if not name:
            self.query_one("#new-tool-status", Label).update("Tool name is required")
            return
        self.dismiss(
            NewToolRequest(
                name=name,
                description=self.query_one("#new-tool-description", Input).value.strip()
                or f"{name} tool",
                category=str(self.query_one("#new-tool-category", Select).value),
            )
        )

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class NewExtensionScreen(ModalScreen[NewExtensionRequest | None]):
    """Modal form for scaffolding an extension."""

    DEFAULT_CSS = NewAgentScreen.DEFAULT_CSS.replace("NewAgentScreen", "NewExtensionScreen")

    def compose(self) -> ComposeResult:
        with Container(id="new-agent-dialog"):
            yield Label("[bold]NEW EXTENSION[/bold]", classes="modal-title")
            with Horizontal(classes="modal-row"):
                yield Label("Name", classes="modal-label")
                yield Input(placeholder="my_extension", id="new-ext-name")
            yield Label("", id="new-ext-status")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="new-ext-cancel")
                yield Button("Create", variant="primary", id="new-ext-create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-ext-cancel":
            self.dismiss(None)
            return
        if event.button.id != "new-ext-create":
            return
        name = _slug(self.query_one("#new-ext-name", Input).value, "")
        if not name:
            self.query_one("#new-ext-status", Label).update("Extension name is required")
            return
        self.dismiss(NewExtensionRequest(name=name))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SelfEditView(Vertical):
    """Tabbed, editable control surface for project/global operator controls."""

    DEFAULT_CSS = """
    SelfEditView {
        width: 100%;
        height: 100%;
        padding: 0;
        background: #0f0d06;
        color: #f6e7a6;
    }
    .self-header {
        height: 3;
        padding: 0 2;
        background: #181206;
        border-bottom: heavy #463815;
    }
    .self-title-text {
        width: 1fr;
        height: 1fr;
        content-align: left middle;
        color: #f0c808;
        text-style: bold;
    }
    .self-header Select {
        background: #1a1608;
        width: 22;
    }
    .self-header SelectCurrent {
        border: tall #4a4020;
        color: #f6e7a6;
        background: #1a1608;
    }
    .self-header Button {
        background: #1a1608;
        border: tall #4a4020;
        min-width: 8;
        color: #f0c808;
    }
    .self-pane {
        height: 1fr;
        padding: 1 2 0 2;
        background: #0f0d06;
    }
    .self-section-label {
        height: 1;
        color: #f0c808;
        text-style: bold;
        margin: 0;
    }
    .self-section-rule {
        color: #3a3218;
        margin: 0;
    }
    .self-row {
        height: auto;
        margin: 0;
    }
    .self-label {
        width: 18;
        height: 3;
        content-align: left middle;
        color: #bca849;
    }
    .self-actions {
        height: auto;
        padding: 0;
        margin-top: 1;
    }
    .self-actions Button {
        margin-right: 1;
    }
    .self-status {
        height: 1;
        color: #7a9c5e;
        margin: 0;
    }
    .tool-field-label {
        height: 1;
        color: #bca849;
        text-style: bold;
        margin: 0;
    }
    .tool-badges {
        height: 1;
        margin: 0 0 1 0;
    }
    .tool-badge {
        height: 1;
        width: auto;
        min-width: 12;
        margin: 0 1 0 0;
        padding: 0 1;
        background: #211a09;
        color: #f6e7a6;
        text-style: bold;
    }
    .tool-badge-accent {
        color: #7a9c5e;
    }
    .tool-description {
        height: auto;
        max-height: 3;
        color: #f6e7a6;
        background: #0b0a05;
        border-left: solid #3a3218;
        padding: 0 1;
    }
    .tool-inline-meta {
        height: auto;
        color: #7a7040;
        background: #0b0a05;
        border-left: solid #3a3218;
        padding: 0 1;
    }
    .agents-layout {
        height: 1fr;
        padding: 1 2 1 2;
        background: #0f0d06;
    }
    .agents-sidebar {
        width: 24;
        height: 1fr;
        margin: 0 2 0 0;
        padding: 0 1 0 0;
        border-right: solid #3a3218;
    }
    .agents-list-title {
        height: 1;
        color: #f0c808;
        text-style: bold;
        margin-bottom: 1;
    }
    .agents-sidebar Button,
    .self-list-sidebar Button {
        width: 100%;
        min-width: 0;
        margin: 0 0 1 0;
        content-align: left middle;
    }
    .agent-editor {
        width: 1fr;
        height: 1fr;
    }
    .self-list-layout {
        height: 1fr;
        padding: 1 2 1 2;
        background: #0f0d06;
    }
    .self-list-sidebar {
        width: 30;
        height: 1fr;
        margin: 0 2 0 0;
        padding: 0 1 0 0;
        border-right: solid #3a3218;
    }
    .self-list-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
        margin: 0 0 1 0;
    }
    .self-sidebar-list {
        height: auto;
        min-height: 100%;
        background: #0f0d06;
    }
    .self-sidebar-list ListItem {
        height: 3;
        padding: 0 1;
        background: #141107;
        color: #f6e7a6;
    }
    .self-sidebar-list ListItem.--highlight,
    .self-sidebar-list ListItem.self-list-item-active {
        background: #2b250f;
        color: #ffe45c;
        text-style: bold;
    }
    .self-sidebar-list ListItem.self-list-item-muted {
        color: #7a7040;
    }
    .self-sidebar-list Label {
        width: 100%;
        height: 1fr;
        content-align: left middle;
    }
    .self-list-new-button {
        background: #17140a;
        border: tall #242424;
        color: #f6e7a6;
        width: 100%;
        min-width: 0;
        margin: 0;
        content-align: center middle;
    }
    .tools-editor-pane,
    .ext-editor-pane {
        width: 1fr;
        height: 1fr;
    }
    .tools-source-bar {
        height: 1;
    }
    .tools-source-title {
        width: auto;
        height: 1;
        color: #f0c808;
        text-style: bold;
    }
    .tool-path {
        width: 1fr;
        height: 1;
        content-align: right middle;
        color: #7a7040;
    }
    .tools-layout {
        height: 1fr;
        margin-top: 0;
    }
    .tools-details {
        height: auto;
        width: 1fr;
    }
    .tools-editor {
        width: 1fr;
        height: 1fr;
        margin-top: 0;
    }
    #tools-source {
        height: 1fr;
    }
    #tools-schema {
        margin: 0;
        background: #0f0d06;
    }
    #tools-schema-text {
        height: 5;
    }
    #ext-text {
        height: 1fr;
    }
    SelfEditView Button {
        background: #222222;
        color: #f6e7a6;
        border: tall #242424;
        min-width: 14;
    }
    SelfEditView Button:hover {
        background: #f0c808;
        color: #0f0d06;
    }
    SelfEditView Button.-primary {
        background: #2b250f;
        border: tall #f0c808;
    }
    SelfEditView Select {
        background: #0b0a05;
        color: #f6e7a6;
    }
    SelfEditView SelectCurrent {
        border: tall #4a3d16;
        color: #f6e7a6;
    }
    .model-select {
        width: 1fr;
    }
    SelfEditView Input {
        background: #0b0a05;
        color: #f6e7a6;
        border: tall #4a3d16;
    }
    SelfEditView Input:focus {
        border: tall #f0c808;
    }
    SelfEditView TextArea {
        background: #0b0a05;
        color: #f6e7a6;
        border: tall #4a3d16;
    }
    SelfEditView TextArea:focus {
        border: tall #f0c808;
    }
    .prompt-editor {
        height: 7;
        scrollbar-size-vertical: 1;
    }
    .tools-grid {
        height: auto;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1 1;
        margin: 0 0 1 0;
    }
    .tools-grid Checkbox {
        height: 3;
        padding: 0 1;
    }
    SelfEditView TabbedContent {
        height: 1fr;
        background: #0f0d06;
    }
    SelfEditView TabbedContent TabPane {
        height: 1fr;
        padding: 0;
    }
    """

    def __init__(self, *, config: Config, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._session = session
        self._store = SelfEditStore(config.working_dir)
        self._scope = self._store.load_default_scope()
        self._agents: dict[str, AgentProfile] = {}
        self._selected_agent_id: str | None = None
        self._extensions: dict[str, ExtensionSource] = {}
        self._tool_sources: dict[str, ToolSource] = {}
        self._selected_tool_name: str | None = None
        self._selected_extension_name: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="self-header"):
            yield Label("SELF-EDIT ////", classes="self-title-text")
            yield Select(
                options=[("Project", "project"), ("Global", "global")],
                value=self._scope,
                id="self-scope",
            )
            yield Button("Exit", id="self-exit")

        with TabbedContent(initial="agents"):
            with TabPane("Agents", id="agents"):
                with Horizontal(id="agents-container", classes="agents-layout"):
                    with Vertical(id="agents-sidebar", classes="agents-sidebar"):
                        yield Label("Agents", classes="agents-list-title")
                        with VerticalScroll(classes="self-list-scroll"):
                            yield ListView(id="agents-list", classes="self-sidebar-list")
                        yield Button(
                            "+ New Agent",
                            id="agent-new",
                            classes="self-list-new-button",
                        )
                    yield Container(id="agent-editor", classes="agent-editor")
            with TabPane("Tools", id="tools"):
                with Horizontal(id="tools-container", classes="self-list-layout"):
                    with Vertical(id="tools-sidebar", classes="self-list-sidebar"):
                        yield Label("Tools", classes="agents-list-title")
                        with VerticalScroll(classes="self-list-scroll"):
                            yield ListView(id="tools-list", classes="self-sidebar-list")
                        yield Button(
                            "+ New Tool",
                            id="tools-new",
                            classes="self-list-new-button",
                        )
                    with Container(id="tools-editor-pane", classes="tools-editor-pane"):
                        with Vertical(classes="self-pane"):
                            with Vertical(classes="tools-layout"):
                                with Vertical(classes="tools-details"):
                                    with Horizontal(classes="tool-badges"):
                                        yield Static("-", id="tools-kind", classes="tool-badge")
                                        yield Static("-", id="tools-category", classes="tool-badge")
                                    yield Label("Description", classes="tool-field-label")
                                    yield Static(
                                        "-",
                                        id="tools-description",
                                        classes="tool-description",
                                        markup=False,
                                    )
                                    yield Label("Inputs", classes="tool-field-label")
                                    yield Static(
                                        "-",
                                        id="tools-required",
                                        classes="tool-inline-meta",
                                    )
                                    yield Collapsible(
                                        TextArea(id="tools-schema-text", read_only=True),
                                        title="Schema",
                                        collapsed=True,
                                        id="tools-schema",
                                    )
                                with Vertical(classes="tools-editor"):
                                    with Horizontal(classes="tools-source-bar"):
                                        yield Label("Source", classes="tools-source-title")
                                        yield Static(
                                            "-",
                                            id="tools-source-path",
                                            classes="tool-path",
                                        )
                                    yield TextArea(id="tools-source")
                            with Horizontal(classes="self-actions"):
                                yield Button("Save", id="tools-save")
                                yield Button("Reload", id="tools-reload")
                                yield Button("Refresh", id="tools-refresh")
                            yield Label("", id="tools-status", classes="self-status")
            with TabPane("Extensions", id="extensions"):
                with Horizontal(id="extensions-container", classes="self-list-layout"):
                    with Vertical(id="extensions-sidebar", classes="self-list-sidebar"):
                        yield Label("Extensions", classes="agents-list-title")
                        with VerticalScroll(classes="self-list-scroll"):
                            yield ListView(id="extensions-list", classes="self-sidebar-list")
                        yield Button(
                            "+ New Extension",
                            id="ext-new",
                            classes="self-list-new-button",
                        )
                    with Container(id="ext-editor-pane", classes="ext-editor-pane"):
                        with Vertical(classes="self-pane"):
                            yield TextArea(id="ext-text")
                            with Horizontal(classes="self-actions"):
                                yield Button("Save", id="ext-save")
                                yield Button("Reload", id="ext-reload")
                            yield Label("", id="ext-status", classes="self-status")
            with TabPane("Config", id="config"):
                with Vertical(classes="self-pane"):
                    with Horizontal(classes="self-row"):
                        yield Label("Provider", classes="self-label")
                        yield Select(
                            options=_provider_options(),
                            value=self._config.provider,
                            id="cfg-provider",
                        )
                    with Horizontal(classes="self-row"):
                        yield Label("Model", classes="self-label")
                        yield Select(
                            options=_model_options(self._config.provider, self._config.model),
                            value=self._config.model,
                            id="cfg-model",
                            classes="model-select",
                        )
                    with Horizontal(classes="self-row"):
                        yield Label("Max turns", classes="self-label")
                        yield Input(value=str(self._config.max_turns), id="cfg-max-turns")
                    yield Label("System prompt")
                    yield TextArea(
                        self._config.system_prompt,
                        id="cfg-system",
                        classes="prompt-editor",
                    )
                    yield Button("Save Config", id="cfg-save")
                    yield Label("", id="cfg-status", classes="self-status")

    async def on_mount(self) -> None:
        await self._refresh_agents()
        await self._refresh_tools()
        await self._refresh_extensions()

    def _status(self, widget_id: str, text: str) -> None:
        self.query_one(f"#{widget_id}", Label).update(text)

    def _rewire_app_callbacks(self) -> None:
        wire = getattr(self.app, "_wire_callbacks", None)
        if callable(wire):
            wire()

    @on(Select.Changed, "#self-scope")
    def _scope_changed(self, event: Select.Changed) -> None:
        self._scope = str(event.value)
        self._store.save_default_scope(self._scope)

    @on(Button.Pressed, "#self-exit")
    async def _exit(self) -> None:
        close = getattr(self.app, "action_close_self_edit", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.stop()

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.stop()

    async def _refresh_agents(self) -> None:
        self._agents = self._store.load_agents()
        if self._selected_agent_id not in self._agents:
            self._selected_agent_id = next(iter(sorted(self._agents)), None)

        list_view = self.query_one("#agents-list", ListView)
        await list_view.clear()
        for agent_id in sorted(self._agents):
            item = _sidebar_item(
                agent_id,
                name=agent_id,
                active=agent_id == self._selected_agent_id,
            )
            await list_view.append(item)
        _select_list_item(list_view, self._selected_agent_id)
        await self._show_agent_editor(self._selected_agent_id)

    async def _show_agent_editor(self, agent_id: str | None) -> None:
        editor = self.query_one("#agent-editor", Container)
        await editor.remove_children()
        if agent_id is None:
            await editor.mount(Static("No agents configured.", classes="self-pane"))
            return
        await editor.mount(self._agent_editor(self._agents[agent_id]))
        _select_list_item(self.query_one("#agents-list", ListView), agent_id)

    def _agent_editor(self, agent: AgentProfile) -> Vertical:
        actions = Horizontal(
            Button("Activate", id=f"agent-activate-{agent.id}"),
            Button("Save", id=f"agent-save-{agent.id}"),
            classes="self-actions",
        )
        tool_names = self._session._registry.names if self._session else []
        return Vertical(
            _row("ID", Input(agent.id, id=f"agent-id-{agent.id}", max_length=3)),
            _row(
                "Provider / model",
                Select(
                    options=_agent_model_options(
                        agent.provider,
                        agent.model,
                        default_provider=self._config.provider,
                        default_model=self._config.model,
                    ),
                    value=_agent_model_value(agent.provider, agent.model)
                    if agent.provider and agent.model
                    else _agent_model_value("", ""),
                    id=f"agent-model-profile-{agent.id}",
                    classes="model-select",
                ),
            ),
            Label("Prompt", classes="self-label"),
            TextArea(agent.prompt, id=f"agent-prompt-{agent.id}", classes="prompt-editor"),
            Label("Allowed tools", classes="self-label"),
            _tools_grid(tool_names, set(agent.allowed_tools), f"agent-tool-{agent.id}"),
            actions,
            Label("", id=f"agent-status-{agent.id}", classes="self-status"),
            classes="self-pane",
        )

    async def _open_new_agent(self) -> None:
        profile = await self.app.push_screen_wait(
            NewAgentScreen(
                default_provider=self._config.provider,
                default_model=self._config.model,
                tool_names=self._session._registry.names if self._session else [],
                existing_ids=set(self._agents),
            )
        )
        if profile is None:
            return
        self._store.save_agent(profile, self._scope)
        self._selected_agent_id = profile.id
        await self._refresh_agents()

    @on(Button.Pressed)
    async def _button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "agent-new":
            await self._open_new_agent()
        elif button_id.startswith("agent-save-"):
            self._save_agent(button_id.removeprefix("agent-save-"))
        elif button_id.startswith("agent-activate-"):
            await self._activate_agent(button_id.removeprefix("agent-activate-"))

    @on(ListView.Selected)
    async def _list_selected(self, event: ListView.Selected) -> None:
        item_name = event.item.name or ""
        list_id = event.list_view.id or ""
        if list_id == "agents-list" and item_name in self._agents:
            self._selected_agent_id = item_name
            await self._show_agent_editor(item_name)
        elif (
            list_id == "tools-list"
            and self._session
            and item_name in self._session._registry.names
        ):
            self._selected_tool_name = item_name
            self._load_tool(item_name)
        elif list_id == "extensions-list" and item_name in self._extensions:
            self._selected_extension_name = item_name
            self._load_extension(item_name)

    @on(Select.Changed)
    def _select_changed(self, event: Select.Changed) -> None:
        select_id = event.select.id or ""
        if select_id == "cfg-provider":
            model = self.query_one("#cfg-model", Select)
            _set_model_options(model, str(event.value), str(model.value))

    def _read_agent_editor(self, original_id: str) -> AgentProfile | None:
        agent_id = self.query_one(f"#agent-id-{original_id}", Input).value.strip().upper()
        if not _AGENT_ID_RE.match(agent_id):
            self._status(
                f"agent-status-{original_id}",
                "Agent ID must be exactly 3 uppercase letters",
            )
            return None
        if agent_id != original_id and agent_id in self._agents:
            self._status(f"agent-status-{original_id}", "Agent ID already exists")
            return None
        provider, model = _split_agent_model(
            str(self.query_one(f"#agent-model-profile-{original_id}", Select).value or "")
        )
        return AgentProfile(
            id=agent_id,
            name=agent_id,
            prompt=self.query_one(f"#agent-prompt-{original_id}", TextArea).text,
            provider=provider,
            model=model,
            allowed_tools=_selected_tools(self, f"agent-tool-{original_id}"),
        )

    def _save_agent(self, original_id: str) -> None:
        profile = self._read_agent_editor(original_id)
        if profile is None:
            return
        self._store.save_agent(profile, self._scope)
        self._agents[profile.id] = profile
        self._status(f"agent-status-{original_id}", f"Saved {profile.id} to {self._scope}")

    async def _activate_agent(self, original_id: str) -> None:
        profile = self._read_agent_editor(original_id)
        if profile is None or self._session is None:
            return
        registry = self._session._registry
        if profile.allowed_tools:
            missing = sorted(set(profile.allowed_tools) - set(registry.names))
            if missing:
                self._status(f"agent-status-{original_id}", f"Unknown tools: {', '.join(missing)}")
                return
            registry = registry.subset(profile.allowed_tools)
        executor = ToolExecutor(registry=registry, policy=self._session._executor._policy)
        if profile.provider:
            self._config.provider = profile.provider
        if profile.model:
            self._config.model = profile.model
        self._config.system_prompt = profile.prompt
        self._session.config = self._config
        await self._session.new_session()
        self._session._loop = AgentLoop(
            llm=self._session._provider,
            executor=executor,
            stream=self._session._stream,
            system_prompt=profile.prompt,
            model=self._config.model,
            max_turns=self._config.max_turns,
        )
        self._rewire_app_callbacks()
        self._status(f"agent-status-{original_id}", f"Activated {profile.id}")

    async def _refresh_tools(self) -> None:
        registry = self._session._registry if self._session else None
        list_view = self.query_one("#tools-list", ListView)
        await list_view.clear()
        if registry is None:
            self._set_tool_meta(category="-", description="No tools", required="-")
            self.query_one("#tools-kind", Static).update("-")
            self.query_one("#tools-source-path", Static).update("-")
            self.query_one("#tools-schema-text", TextArea).text = "{}"
            self.query_one("#tools-source", TextArea).text = ""
            return

        self._tool_sources = self._discover_tool_sources(registry)
        if self._selected_tool_name not in registry.names:
            self._selected_tool_name = next(iter(registry.names), None)

        for name in registry.names:
            source = self._tool_sources.get(name)
            label = f"{name} *" if source and source.path else name
            item = _sidebar_item(
                label,
                name=name,
                active=name == self._selected_tool_name,
                muted=source is None or source.path is None,
            )
            await list_view.append(item)
        _select_list_item(list_view, self._selected_tool_name)

        if self._selected_tool_name:
            self._load_tool(self._selected_tool_name)

    def _discover_tool_sources(self, registry: ToolRegistry) -> dict[str, ToolSource]:
        builtin = getattr(self._session, "_builtin_tool_names", set()) if self._session else set()
        extension_paths = self._extension_paths()
        sources: dict[str, ToolSource] = {}
        for name in registry.names:
            sources[name] = ToolSource(
                name=name,
                path=None if name in builtin else _find_tool_source(name, extension_paths),
            )
        return sources

    def _extension_paths(self) -> list[Path]:
        paths: list[Path] = []
        for base in (
            Path.home() / ".taui" / "extensions",
            self._config.working_dir / ".taui" / "extensions",
        ):
            if base.is_dir():
                paths.extend(sorted(base.glob("*.py")))
        return paths

    def _load_tool(self, name: str) -> None:
        if not self._session:
            return
        self._selected_tool_name = name
        tool = self._session._registry.get(name)
        required = ""
        if isinstance(tool.schema, dict):
            required = ", ".join(str(x) for x in tool.schema.get("required", []))
        schema = json.dumps(tool.schema, indent=2) if isinstance(tool.schema, dict) else "{}"
        self._set_tool_meta(
            category=tool.category.value,
            description=tool.description,
            required=required or "-",
        )
        self.query_one("#tools-schema-text", TextArea).text = schema
        self.query_one("#tools-schema", Collapsible).collapsed = True
        source = self._tool_sources.get(name)
        editor = self.query_one("#tools-source", TextArea)
        if source and source.path:
            self.query_one("#tools-kind", Static).update("Editable")
            self.query_one("#tools-kind", Static).add_class("tool-badge-accent")
            self.query_one("#tools-source-path", Static).update(source.path.name)
            editor.read_only = False
            editor.text = source.path.read_text(encoding="utf-8")
            self._status("tools-status", f"Source: {source.path.name}")
        else:
            self.query_one("#tools-kind", Static).update("Built-in")
            self.query_one("#tools-kind", Static).remove_class("tool-badge-accent")
            self.query_one("#tools-source-path", Static).update("source locked")
            editor.read_only = True
            editor.text = "Built-in tools are edited in source code, not self-edit."
            self._status("tools-status", "Select an extension-backed tool to edit source.")
        _select_list_item(self.query_one("#tools-list", ListView), name)

    def _set_tool_meta(
        self,
        *,
        category: str,
        description: str,
        required: str,
    ) -> None:
        self.query_one("#tools-category", Static).update(category)
        self.query_one("#tools-description", Static).update(description)
        self.query_one("#tools-required", Static).update(required)

    @on(Button.Pressed, "#tools-refresh")
    async def _tools_refresh(self) -> None:
        await self._refresh_tools()

    @on(Button.Pressed, "#tools-save")
    def _save_tool_source(self) -> None:
        name = self._selected_tool_name or ""
        source = self._tool_sources.get(name)
        if source is None or source.path is None:
            self._status("tools-status", "No editable tool source selected")
            return
        source.path.write_text(self.query_one("#tools-source", TextArea).text, encoding="utf-8")
        self._status("tools-status", f"Saved {source.path.name}")

    @on(Button.Pressed, "#tools-reload")
    async def _reload_tools(self) -> None:
        if self._session:
            loaded = self._session.reload_extensions()
            self._rewire_app_callbacks()
            await self._refresh_tools()
            await self._refresh_extensions()
            self._status("tools-status", f"Reloaded {len(loaded)} extension(s)")

    @on(Button.Pressed, "#tools-new")
    async def _new_tool(self) -> None:
        request = await self.app.push_screen_wait(NewToolScreen())
        if request is None:
            return
        base = _scope_extension_base(self._config.working_dir, self._scope)
        path = _unique_path(base, f"tool_{request.name}", ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_tool_extension_template(request), encoding="utf-8")
        if self._session:
            self._session.reload_extensions()
            self._rewire_app_callbacks()
        self._selected_tool_name = request.name
        await self._refresh_tools()
        await self._refresh_extensions()
        self._status("tools-status", f"Created {path.name}")

    async def _refresh_extensions(self) -> None:
        reg = ExtensionRegistry(self._config.working_dir, include_builtins=True)
        reg.discover()
        self._merge_loaded_extension_state(reg)
        self._extensions = {
            ext.name: ExtensionSource(
                name=ext.name,
                path=ext.path,
                scope=ext.scope,
                description=ext.description,
                loaded=ext.loaded,
                error=ext.error,
            )
            for ext in reg.list_all()
        }
        list_view = self.query_one("#extensions-list", ListView)
        await list_view.clear()
        if self._selected_extension_name not in self._extensions:
            self._selected_extension_name = next(iter(sorted(self._extensions)), None)

        for name, ext in sorted(self._extensions.items()):
            item = _sidebar_item(
                _extension_sidebar_label(ext),
                name=name,
                active=name == self._selected_extension_name,
                muted=ext.path is None,
            )
            await list_view.append(item)
        _select_list_item(list_view, self._selected_extension_name)

        if self._selected_extension_name:
            self._load_extension(self._selected_extension_name)
        else:
            editor = self.query_one("#ext-text", TextArea)
            editor.read_only = True
            editor.text = ""

    def _merge_loaded_extension_state(self, reg: ExtensionRegistry) -> None:
        session_reg = getattr(self._session, "_ext_registry", None)
        if session_reg is None:
            return
        for session_ext in session_reg.list_all():
            ext = reg.get(session_ext.name)
            if ext is None:
                continue
            ext.loaded = session_ext.loaded
            ext.error = session_ext.error

    def _load_extension(self, name: str) -> None:
        ext = self._extensions.get(name)
        if ext is None:
            return

        self._selected_extension_name = name
        editor = self.query_one("#ext-text", TextArea)
        if ext.path and ext.path.exists():
            editor.read_only = False
            editor.text = ext.path.read_text(encoding="utf-8")
            self._status("ext-status", f"Source: {ext.path.name}")
            self._mark_extension_button_active(name)
            return

        editor.read_only = True
        editor.text = _builtin_extension_summary(ext)
        self._status("ext-status", f"{ext.name} is a built-in extension")
        self._mark_extension_button_active(name)

    def _mark_extension_button_active(self, name: str) -> None:
        _select_list_item(self.query_one("#extensions-list", ListView), name)

    @on(Button.Pressed, "#ext-new")
    async def _new_ext(self) -> None:
        request = await self.app.push_screen_wait(NewExtensionScreen())
        if request is None:
            return
        base = _scope_extension_base(self._config.working_dir, self._scope)
        path = _unique_path(base, request.name, ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_extension_template(), encoding="utf-8")
        self._selected_extension_name = request.name
        await self._refresh_extensions()
        self._status("ext-status", f"Created {path.name}")

    @on(Button.Pressed, "#ext-save")
    def _save_ext(self) -> None:
        name = self._selected_extension_name or ""
        ext = self._extensions.get(name)
        if ext is None:
            self._status("ext-status", "No extension selected")
            return
        if ext.path is None:
            self._status("ext-status", "Built-in extensions are read-only")
            return
        ext.path.write_text(self.query_one("#ext-text", TextArea).text, encoding="utf-8")
        self._status("ext-status", f"Saved {name}")

    @on(Button.Pressed, "#ext-reload")
    async def _reload_ext(self) -> None:
        if self._session:
            loaded = self._session.reload_extensions()
            self._rewire_app_callbacks()
            await self._refresh_tools()
            await self._refresh_extensions()
            self._status("ext-status", f"Reloaded {len(loaded)} extension(s)")

    @on(Button.Pressed, "#cfg-save")
    def _save_cfg(self) -> None:
        provider = str(self.query_one("#cfg-provider", Select).value)
        model = str(self.query_one("#cfg-model", Select).value)
        max_turns_raw = self.query_one("#cfg-max-turns", Input).value.strip()
        try:
            max_turns = int(max_turns_raw)
        except ValueError:
            self._status("cfg-status", "max_turns must be an integer")
            return
        self._config.provider = provider
        self._config.model = model
        self._config.max_turns = max_turns
        self._config.system_prompt = self.query_one("#cfg-system", TextArea).text
        if self._session:
            self._session.config = self._config
            self._session._loop._model = model
            self._session._loop._max_turns = max_turns
        self._status("cfg-status", "Runtime config updated")


def _provider_options() -> list[tuple[str, str]]:
    return [("", ""), ("copilot", "copilot"), ("codex", "codex")]


def _agent_model_value(provider: str, model: str) -> str:
    return f"{provider}{_AGENT_MODEL_SEP}{model}"


def _split_agent_model(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    if _AGENT_MODEL_SEP not in value:
        return "", value
    provider, model = value.split(_AGENT_MODEL_SEP, 1)
    return provider, model


def _agent_model_options(
    selected_provider: str,
    selected_model: str,
    *,
    default_provider: str,
    default_model: str,
) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    inherit_label = "Inherit"
    if default_provider or default_model:
        inherit_label = f"Inherit ({default_provider or '-'} / {default_model or '-'})"
    options.append((inherit_label, _agent_model_value("", "")))

    pairs: list[tuple[str, str]] = []
    if selected_provider and selected_model:
        pairs.append((selected_provider, selected_model))
    for provider in ("copilot", "codex"):
        default = DEFAULT_MODELS.get(provider, "")
        if default:
            pairs.append((provider, default))
        pairs.extend((provider, model) for model in PREFERRED_MODELS.get(provider, []))

    seen: set[tuple[str, str]] = set()
    for provider, model in pairs:
        pair = (provider, model)
        if not provider or not model or pair in seen:
            continue
        seen.add(pair)
        options.append((f"{provider} / {model}", _agent_model_value(provider, model)))
    return options


def _model_options(
    provider: str,
    selected: str = "",
    *,
    inherit_model: str = "",
) -> list[tuple[str, str]]:
    models: list[str] = []
    if selected:
        models.append(selected)
    default = DEFAULT_MODELS.get(provider, "")
    if default:
        models.append(default)
    models.extend(PREFERRED_MODELS.get(provider, []))

    seen: set[str] = set()
    options: list[tuple[str, str]] = []
    empty_label = f"Inherit ({inherit_model})" if inherit_model else ""
    options.append((empty_label, ""))
    for model in models:
        if model and model not in seen:
            seen.add(model)
            options.append((model, model))
    return options


def _set_model_options(
    select: Select,
    provider: str,
    selected: str,
    *,
    inherit_model: str = "",
) -> None:
    options = _model_options(provider, selected, inherit_model=inherit_model)
    values = {value for _, value in options}
    select.set_options(options)
    select.value = selected if selected in values else ""


def _tools_grid(tool_names: list[str], selected: set[str], prefix: str) -> Grid:
    return Grid(
        *[
            Checkbox(
                name,
                value=name in selected,
                name=name,
                id=f"{prefix}-{index}",
                classes="tools-checkbox",
                compact=False,
            )
            for index, name in enumerate(tool_names)
        ],
        classes="tools-grid",
    )


def _selected_tools(root, prefix: str | None = None) -> list[str]:
    selected: list[str] = []
    for checkbox in root.query(Checkbox):
        checkbox_id = checkbox.id or ""
        if prefix is not None and not checkbox_id.startswith(f"{prefix}-"):
            continue
        if checkbox.value and checkbox.name:
            selected.append(str(checkbox.name))
    return selected


def _row(label: str, widget) -> Horizontal:
    return Horizontal(Label(label, classes="self-label"), widget, classes="self-row")


def _sidebar_item(
    label: str,
    *,
    name: str,
    active: bool = False,
    muted: bool = False,
) -> ListItem:
    classes = []
    if active:
        classes.append("self-list-item-active")
    if muted:
        classes.append("self-list-item-muted")
    return ListItem(Label(label, markup=False), name=name, classes=" ".join(classes) or None)


def _select_list_item(list_view: ListView, selected_name: str | None) -> None:
    selected_index: int | None = None
    for index, item in enumerate(list_view.children):
        if not isinstance(item, ListItem):
            continue
        if item.name == selected_name:
            selected_index = index
            item.add_class("self-list-item-active")
        else:
            item.remove_class("self-list-item-active")
    list_view.index = selected_index


def _find_tool_source(tool_name: str, extension_paths: list[Path]) -> Path | None:
    patterns = (
        f'name: str = "{tool_name}"',
        f"name: str = '{tool_name}'",
        f'name = "{tool_name}"',
        f"name = '{tool_name}'",
    )
    preferred = {f"tool_{tool_name}.py", f"{tool_name}.py"}
    for path in extension_paths:
        if path.name in preferred:
            return path
    for path in extension_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(pattern in content for pattern in patterns):
            return path
    return None


def _extension_option_label(ext: ExtensionSource) -> str:
    status = "error" if ext.error else ("loaded" if ext.loaded else "not loaded")
    if ext.path is None:
        return f"{ext.name} [builtin] - {status}"
    return f"{ext.name} [{ext.scope}] - {status} - {ext.path.name}"


def _extension_sidebar_label(ext: ExtensionSource) -> str:
    marker = "!" if ext.error else ("*" if ext.loaded else "-")
    scope = "builtin" if ext.path is None else ext.scope
    return f"{marker} {ext.name} [{scope}]"


def _builtin_extension_summary(ext: ExtensionSource) -> str:
    lines = [
        f"{ext.name}",
        "",
        ext.description or "Taui built-in extension.",
        "",
        "Scope: builtin",
        f"Status: {'error' if ext.error else ('loaded' if ext.loaded else 'not loaded')}",
        "",
        "Built-in extensions are part of Taui and are read-only in self-edit.",
        "Create a project or global extension to customize behavior.",
    ]
    if ext.error:
        lines.extend(["", f"Error: {ext.error}"])
    return "\n".join(lines)


def _tool_extension_template(request: NewToolRequest) -> str:
    class_name = "".join(part.capitalize() for part in request.name.split("_")) + "Tool"
    return f'''from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class {class_name}:
    name: str = "{request.name}"
    description: str = "{request.description}"
    category: ToolCategory = ToolCategory.{request.category.upper()}
    schema: dict[str, Any] = field(default_factory=lambda: {{
        "type": "object",
        "properties": {{
            "input": {{"type": "string", "description": "Tool input."}},
        }},
        "required": ["input"],
    }})

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(f"received: {{arguments.get('input', '')}}")


def register(tools, commands, hooks):
    tools.register({class_name}())
'''


def _extension_template() -> str:
    return '''def register(tools, commands, hooks):
    """Register extension components."""
    return None
'''
