"""Tool detail/policy editor widget for the config screen."""

from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, Static, TextArea

from taui.tools.base import Tool


class ToolEditor(Static):
    """Read-only detail pane for a tool with policy override."""

    DEFAULT_CSS = """
    ToolEditor {
        height: auto;
        padding: 1 0;
    }
    .tool-section-title {
        text-style: bold;
        padding: 1 0 0 0;
        color: #f0c674;
    }
    .tool-info-row {
        height: auto;
        margin: 0 0 0 0;
    }
    .tool-info-label {
        width: 14;
        color: $text-muted;
    }
    .tool-info-value {
        width: 1fr;
    }
    #tool-schema-area {
        height: 12;
        border: solid $surface-lighten-1;
        margin: 1 0;
    }
    .tool-desc {
        padding: 0 0 1 0;
        color: $text;
    }
    """

    def __init__(self, tool: Tool) -> None:
        super().__init__()
        self._tool = tool

    def compose(self) -> ComposeResult:
        t = self._tool
        yield Static(f"Tool: {t.name}", classes="tool-section-title")
        yield Static(t.description, classes="tool-desc")

        with Horizontal(classes="tool-info-row"):
            yield Label("Category", classes="tool-info-label")
            yield Static(str(t.category.value), classes="tool-info-value")

        guidelines = getattr(t, "guidelines", None)
        if guidelines:
            yield Static("Guidelines", classes="tool-section-title")
            yield Static(str(guidelines), classes="tool-desc")

        yield Static("Schema", classes="tool-section-title")
        schema_text = json.dumps(t.schema, indent=2)
        yield TextArea(
            schema_text,
            id="tool-schema-area",
            language="json",
            read_only=True,
        )
