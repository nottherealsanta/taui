"""Agent profile editor widget for the config screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from taui.self_edit.store import AgentProfile, ToolConfig


class AgentEditor(Static):
    """Editor pane for a single agent profile."""

    DEFAULT_CSS = """
    AgentEditor {
        height: auto;
        padding: 1 0;
    }
    .agent-field-row {
        height: 3;
        margin: 0 0 0 0;
    }
    .agent-field-label {
        width: 16;
        padding: 1 1 0 0;
        color: $text-muted;
    }
    .agent-field-input {
        width: 1fr;
    }
    #agent-prompt-area {
        height: 12;
        border: solid $surface-lighten-1;
        margin: 0 0 1 0;
    }
    .agent-section-title {
        text-style: bold;
        padding: 1 0 0 0;
        margin: 0;
        color: #f0c674;
    }
    .agent-section-hint {
        color: $text-muted;
        margin: 0 0 0 0;
    }
    .tool-checkbox-grid {
        layout: horizontal;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .tool-cb {
        width: auto;
        height: 1;
        margin: 0 2 0 0;
        padding: 0;
    }
    .tool-cb > .toggle--label {
        padding: 0;
    }
    .agent-actions {
        height: 3;
        padding: 1 0;
    }
    .policy-grid {
        height: auto;
        padding: 0;
    }
    .policy-row {
        height: 3;
        margin: 0;
        padding: 0;
    }
    .policy-label {
        width: 14;
        padding: 1 1 0 0;
        color: $text-muted;
    }
    .policy-select {
        width: 16;
    }
    """

    def __init__(
        self,
        profile: AgentProfile,
        *,
        all_tool_names: list[str],
        is_active: bool = False,
    ) -> None:
        super().__init__()
        self._profile = profile
        self._all_tool_names = all_tool_names
        self._is_active = is_active

    def compose(self) -> ComposeResult:
        p = self._profile

        yield Static(f"Agent: {p.id}", classes="agent-section-title")

        with Horizontal(classes="agent-field-row"):
            yield Label("Name", classes="agent-field-label")
            yield Input(p.name, id="agent-name", classes="agent-field-input")

        with Horizontal(classes="agent-field-row"):
            yield Label("Provider", classes="agent-field-label")
            yield Input(
                p.provider,
                id="agent-provider",
                classes="agent-field-input",
                placeholder="(inherit default)",
            )

        with Horizontal(classes="agent-field-row"):
            yield Label("Model", classes="agent-field-label")
            yield Input(
                p.model,
                id="agent-model",
                classes="agent-field-input",
                placeholder="(inherit default)",
            )

        yield Static("System Prompt", classes="agent-section-title")
        yield TextArea(p.prompt, id="agent-prompt-area", language="markdown")

        yield Static("Allowed Tools", classes="agent-section-title")
        yield Static(
            "empty = all tools allowed",
            classes="agent-section-hint",
        )
        allowed = set(p.allowed_tools) if p.allowed_tools else set()
        all_allowed = not p.allowed_tools
        with Horizontal(classes="tool-checkbox-grid"):
            for name in self._all_tool_names:
                checked = all_allowed or name in allowed
                yield Checkbox(
                    name,
                    value=checked,
                    id=f"tool-cb-{name}",
                    classes="tool-cb",
                )

        yield Static("Tool Policies", classes="agent-section-title")
        yield Static(
            "per-tool execution policy for this agent",
            classes="agent-section-hint",
        )
        with Vertical(classes="policy-grid"):
            for name in self._all_tool_names:
                tc = p.tool_config.get(name)
                current_policy = tc.policy if tc else "auto"
                with Horizontal(classes="policy-row"):
                    yield Label(name, classes="policy-label")
                    yield Select(
                        [
                            ("auto", "auto"),
                            ("confirm", "confirm"),
                            ("deny", "deny"),
                        ],
                        value=current_policy,
                        id=f"policy-{name}",
                        classes="policy-select",
                        allow_blank=False,
                    )

        with Horizontal(classes="agent-actions"):
            if not self._is_active:
                yield Button("Activate", id="btn-activate", variant="primary")
            else:
                yield Static("[green]● Active[/green]", markup=True)
            yield Button("Delete", id="btn-delete", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-activate":
            profile = self.collect()
            if profile:
                self.screen.post_message(self.screen.AgentActivated(profile))
        elif event.button.id == "btn-delete":
            self.screen._pending.deleted_agents.add(self._profile.id)
            self.notify(
                f"Agent {self._profile.id} marked for deletion (save to apply)"
            )

    def collect(self) -> AgentProfile | None:
        """Collect current form state into an AgentProfile."""
        try:
            name = self.query_one("#agent-name", Input).value
            provider = self.query_one("#agent-provider", Input).value
            model = self.query_one("#agent-model", Input).value
            prompt = self.query_one("#agent-prompt-area", TextArea).text

            # Collect allowed tools from checkboxes
            allowed: list[str] = []
            all_checked = True
            for tool_name in self._all_tool_names:
                try:
                    cb = self.query_one(f"#tool-cb-{tool_name}", Checkbox)
                    if cb.value:
                        allowed.append(tool_name)
                    else:
                        all_checked = False
                except Exception:
                    pass
            # If all are checked, store empty list (= all allowed)
            if all_checked:
                allowed = []

            # Collect tool policies
            tool_config: dict[str, ToolConfig] = {}
            for tool_name in self._all_tool_names:
                try:
                    sel = self.query_one(f"#policy-{tool_name}", Select)
                    policy = str(sel.value)
                    if policy != "auto":
                        existing = self._profile.tool_config.get(tool_name)
                        restrictions = (
                            existing.param_restrictions if existing else {}
                        )
                        tool_config[tool_name] = ToolConfig(
                            policy=policy,
                            param_restrictions=restrictions,
                        )
                except Exception:
                    pass

            return AgentProfile(
                id=self._profile.id,
                name=name,
                prompt=prompt,
                provider=provider,
                model=model,
                allowed_tools=allowed,
                prompt_path=self._profile.prompt_path,
                tool_config=tool_config,
            )
        except Exception:
            return None
