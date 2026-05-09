"""General TAUI configuration editor widget."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Checkbox, Input, Label, Static, TextArea

from taui.config import Config


class GeneralEditor(Static):
    """Editor pane for general TAUI settings."""

    DEFAULT_CSS = """
    GeneralEditor {
        height: auto;
        padding: 1 0;
    }
    .general-section-title {
        text-style: bold;
        padding: 1 0 0 0;
        color: #f0c674;
    }
    .general-field-row {
        height: 3;
        margin: 0 0 1 0;
    }
    .general-field-label {
        width: 18;
        padding: 1 1 0 0;
        color: $text-muted;
    }
    .general-field-input {
        width: 1fr;
    }
    #general-system-prompt {
        height: 12;
        border: solid $surface-lighten-1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        c = self._config
        yield Static("General Settings", classes="general-section-title")

        with Horizontal(classes="general-field-row"):
            yield Label("Provider", classes="general-field-label")
            yield Input(
                c.provider, id="gen-provider", classes="general-field-input"
            )

        with Horizontal(classes="general-field-row"):
            yield Label("Model", classes="general-field-label")
            yield Input(
                c.model, id="gen-model", classes="general-field-input"
            )

        with Horizontal(classes="general-field-row"):
            yield Label("Max Turns", classes="general-field-label")
            yield Input(
                str(c.max_turns), id="gen-max-turns", classes="general-field-input"
            )

        with Horizontal(classes="general-field-row"):
            yield Label("Working Dir", classes="general-field-label")
            yield Static(
                str(c.working_dir), classes="general-field-input"
            )

        yield Checkbox(
            "Verbose tool output",
            value=c.verbose_tools,
            id="gen-verbose",
        )

        yield Static("System Prompt", classes="general-section-title")
        yield Static(
            "[dim]Default system prompt template[/dim]",
            markup=True,
        )
        yield TextArea(
            c.system_prompt,
            id="general-system-prompt",
            language="markdown",
        )

    def collect(self) -> dict[str, Any]:
        """Collect current form state as a dict of changed config fields."""
        changes: dict[str, Any] = {}
        try:
            provider = self.query_one("#gen-provider", Input).value
            if provider != self._config.provider:
                changes["provider"] = provider

            model = self.query_one("#gen-model", Input).value
            if model != self._config.model:
                changes["model"] = model

            try:
                max_turns = int(self.query_one("#gen-max-turns", Input).value)
                if max_turns != self._config.max_turns:
                    changes["max_turns"] = max_turns
            except ValueError:
                pass

            verbose = self.query_one("#gen-verbose", Checkbox).value
            if verbose != self._config.verbose_tools:
                changes["verbose_tools"] = verbose

            prompt = self.query_one("#general-system-prompt", TextArea).text
            if prompt != self._config.system_prompt:
                changes["system_prompt"] = prompt
        except Exception:
            pass
        return changes
