"""Info2 – unified expandable panel above the chat input.

Modes:
- completions: slash-command autocomplete list
- models: inline model picker
- agents: inline agent picker
- context: inline context tree
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Tree

from taui.agent.context import estimate_message_tokens, estimate_total_tokens

type Completion = tuple[str, str, bool]  # (name, description, accepts_args)


class Info2Mode(Enum):
    HIDDEN = auto()
    COMPLETIONS = auto()
    MODELS = auto()
    AGENTS = auto()
    CONTEXT = auto()


class Info2Item(Static):
    """A single row in the Info2 panel."""

    DEFAULT_CSS = """
    Info2Item {
        height: 1;
        padding: 0 0 0 1;
        color: $text-muted;
    }
    Info2Item.highlighted {
        background: $surface-lighten-1;
        color: $text;
    }
    """


class Info2(ScrollableContainer):
    """Unified expandable panel for completions, pickers, and context views."""

    DEFAULT_CSS = """
    Info2 {
        height: auto;
        max-height: 8;
        display: none;
        scrollbar-size: 1 1;
        padding: 0 0 0 1;
        margin: 0 1;
        background: $surface;
        border: tall $surface-darken-1;
        border-top: none;
        border-bottom: none;
    }
    Info2.active {
        display: block;
    }
    Info2 Tree {
        height: auto;
        background: transparent;
    }
    """

    selected_index: reactive[int] = reactive(0)

    # ── Messages ───────────────────────────────────────────────────────

    class CompletionSelected(Message):
        """A slash-command completion was accepted."""

        def __init__(self, value: str, accepts_args: bool) -> None:
            super().__init__()
            self.value = value
            self.accepts_args = accepts_args

    class ModelSelected(Message):
        """A model was selected inline."""

        def __init__(self, model_id: str) -> None:
            super().__init__()
            self.model_id = model_id

    class AgentSelected(Message):
        """An agent was selected inline."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    class Dismissed(Message):
        """Panel was dismissed without selection."""

    # ── Init ───────────────────────────────────────────────────────────

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode: Info2Mode = Info2Mode.HIDDEN
        self._items: list[Completion] = []
        self._model_items: list[dict] = []
        self._agent_items: list = []  # list[AgentProfile]
        self._current_marker: str = ""
        self._prefix: str = "/"
        self._context_tree: Tree[str] | None = None

    def compose(self) -> ComposeResult:
        return iter(())

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def mode(self) -> Info2Mode:
        return self._mode

    @property
    def is_active(self) -> bool:
        return self._mode != Info2Mode.HIDDEN

    def show_completions(
        self, items: list[Completion], prefix: str = "/"
    ) -> None:
        """Show slash-command completions."""
        if not items:
            self.hide()
            return
        self._mode = Info2Mode.COMPLETIONS
        self._items = items
        self._prefix = prefix
        self.selected_index = 0
        self._rebuild_completions()
        self.add_class("active")

    def show_models(self, models: list[dict], current: str) -> None:
        """Show inline model picker."""
        if not models:
            return
        self._mode = Info2Mode.MODELS
        self._model_items = models[:50]
        self._current_marker = current
        self.selected_index = 0
        # Try to pre-select current model
        for i, m in enumerate(self._model_items):
            if str(m.get("id", "")) == current:
                self.selected_index = i
                break
        self._rebuild_models()
        self.add_class("active")

    def show_agents(self, agents: list, current: str) -> None:
        """Show inline agent picker."""
        if not agents:
            return
        self._mode = Info2Mode.AGENTS
        self._agent_items = agents[:50]
        self._current_marker = current.upper()
        self.selected_index = 0
        for i, a in enumerate(self._agent_items):
            if a.id.upper() == self._current_marker:
                self.selected_index = i
                break
        self._rebuild_agents()
        self.add_class("active")

    def show_context_tree(self, messages: list[Any], max_tokens: int) -> None:
        """Show an inline context tree grouped by message role."""
        self._mode = Info2Mode.CONTEXT
        self._context_tree = self._build_context_tree(messages, max_tokens)
        self.selected_index = 0
        self.remove_children()
        self.mount(self._context_tree)
        self.call_after_refresh(self._context_tree.focus)
        self.add_class("active")

    def hide(self) -> None:
        """Hide the panel."""
        self._mode = Info2Mode.HIDDEN
        self._items = []
        self._model_items = []
        self._agent_items = []
        self._context_tree = None
        self.remove_children()
        self.remove_class("active")

    # ── Navigation ─────────────────────────────────────────────────────

    @property
    def current_value(self) -> str | None:
        """Return the selected item's value string."""
        match self._mode:
            case Info2Mode.COMPLETIONS:
                if self._items and 0 <= self.selected_index < len(self._items):
                    return self._items[self.selected_index][0]
            case Info2Mode.MODELS:
                if self._model_items and 0 <= self.selected_index < len(self._model_items):
                    return str(self._model_items[self.selected_index]["id"])
            case Info2Mode.AGENTS:
                if self._agent_items and 0 <= self.selected_index < len(self._agent_items):
                    return self._agent_items[self.selected_index].id
            case Info2Mode.CONTEXT:
                return None
        return None

    @property
    def current_accepts_args(self) -> bool:
        """For completion mode: does the selected command accept args?"""
        if self._mode == Info2Mode.COMPLETIONS:
            if self._items and 0 <= self.selected_index < len(self._items):
                return self._items[self.selected_index][2]
        return True

    def move_up(self) -> None:
        count = self._item_count()
        if count:
            self.selected_index = (self.selected_index - 1) % count
            self._update_highlight()

    def move_down(self) -> None:
        count = self._item_count()
        if count:
            self.selected_index = (self.selected_index + 1) % count
            self._update_highlight()

    def accept(self) -> None:
        """Accept the current selection and post the appropriate message."""
        match self._mode:
            case Info2Mode.COMPLETIONS:
                value = self.current_value
                if value is not None:
                    self.post_message(
                        self.CompletionSelected(value, self.current_accepts_args)
                    )
            case Info2Mode.MODELS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.ModelSelected(value))
                self.hide()
            case Info2Mode.AGENTS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.AgentSelected(value))
                self.hide()
            case Info2Mode.CONTEXT:
                if self._context_tree is not None:
                    self._context_tree.action_toggle_node()

    def dismiss(self) -> None:
        """Dismiss without selection."""
        self.hide()
        self.post_message(self.Dismissed())

    # ── Internal ───────────────────────────────────────────────────────

    def _item_count(self) -> int:
        match self._mode:
            case Info2Mode.COMPLETIONS:
                return len(self._items)
            case Info2Mode.MODELS:
                return len(self._model_items)
            case Info2Mode.AGENTS:
                return len(self._agent_items)
            case Info2Mode.CONTEXT:
                return 0
        return 0

    def _rebuild_completions(self) -> None:
        self.remove_children()
        for i, (name, desc, _) in enumerate(self._items):
            label = f"{self._prefix}{name:<14s} {desc}"
            item = Info2Item(label)
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _rebuild_models(self) -> None:
        self.remove_children()
        for i, model in enumerate(self._model_items):
            item = Info2Item(self._model_label(model))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _rebuild_agents(self) -> None:
        self.remove_children()
        for i, agent in enumerate(self._agent_items):
            item = Info2Item(self._agent_label(agent))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _build_context_tree(self, messages: list[Any], max_tokens: int) -> Tree[str]:
        total_tokens = estimate_total_tokens(messages)
        pct = (total_tokens / max_tokens * 100) if max_tokens else 0.0
        tree: Tree[str] = Tree(
            f"Context {total_tokens:,}/{max_tokens:,} tokens ({pct:.1f}%)",
            id="context-tree",
        )
        tree.root.expand()

        groups = [
            ("system", "System"),
            ("user", "User Messages"),
            ("assistant", "Assistant"),
            ("tool", "Tool Results"),
        ]
        grouped = {
            role: [
                (index, message)
                for index, message in enumerate(messages, start=1)
                if getattr(message, "role", "unknown") == role
            ]
            for role, _ in groups
        }

        for role, label in groups:
            entries = grouped[role]
            tokens = sum(estimate_message_tokens(message) for _, message in entries)
            group = tree.root.add(
                f"{label} ({len(entries)} messages, {tokens:,} tokens)",
                expand=True,
            )
            if not entries:
                group.add_leaf("(none)")
                continue
            for index, message in entries:
                message_tokens = estimate_message_tokens(message)
                preview = self._message_preview(message)
                group.add_leaf(f"#{index}  {message_tokens:,} tokens  {preview}")
        return tree

    def _model_label(self, model: dict) -> Text:
        model_id = str(model.get("id", ""))
        context = int(model.get("context", 0) or 0)
        ctx = f"{context // 1000}k" if context else "?"
        reasoning = " reasoning" if model.get("reasoning") else ""
        marker = " ◀" if model_id == self._current_marker else ""
        text = Text()
        text.append(f"{model_id:<45s}", style="bold cyan" if marker else "white")
        text.append(f"  {ctx:>6s} ctx{reasoning}{marker}", style="dim")
        return text

    def _agent_label(self, agent) -> Text:
        model = "/".join(
            part for part in (agent.provider, agent.model) if part
        ) or "-"
        marker = " ◀" if agent.id.upper() == self._current_marker else ""
        text = Text()
        text.append(f"{agent.id:<5s}", style="bold cyan" if marker else "white")
        text.append(f"{agent.name:<24s}", style="white")
        text.append(f"  {model}{marker}", style="dim")
        return text

    @staticmethod
    def _message_preview(message: Any, limit: int = 80) -> str:
        content = getattr(message, "content", None) or ""
        if not content and getattr(message, "tool_calls", None):
            names = [
                str(getattr(call, "name", "tool"))
                for call in (getattr(message, "tool_calls", None) or [])
            ]
            content = "tool calls: " + ", ".join(names)
        if not content and getattr(message, "name", None):
            content = str(getattr(message, "name"))
        preview = " ".join(str(content).split())
        if len(preview) > limit:
            return preview[: limit - 3] + "..."
        return preview or "(empty)"

    def _update_highlight(self) -> None:
        items = self.query(Info2Item)
        for i, item in enumerate(items):
            if i == self.selected_index:
                item.add_class("highlighted")
            else:
                item.remove_class("highlighted")
        # Scroll highlighted item into view
        try:
            highlighted = list(items)[self.selected_index]
            self.scroll_to_widget(highlighted, animate=False)
        except (IndexError, Exception):
            pass
