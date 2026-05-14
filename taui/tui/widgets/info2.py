"""Info2 – unified expandable panel above the chat input.

Modes:
- completions: slash-command autocomplete list
- models: inline model picker
- agents: inline agent picker
- sessions: inline session picker
- context: inline context tree
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Tree

from taui.agent.context import estimate_message_tokens, estimate_total_tokens
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec

type Completion = tuple[str, str, bool]  # (name, description, accepts_args)


@dataclass(slots=True)
class ApprovalResult:
    """Result from an approval prompt."""

    approved: bool
    pattern: str | None = None
    tool_scope: str | None = None


class Info2Mode(Enum):
    HIDDEN = auto()
    COMPLETIONS = auto()
    MODELS = auto()
    AGENTS = auto()
    SESSIONS = auto()
    CONTEXT = auto()
    APPROVAL = auto()
    QUESTIONS = auto()


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

    can_focus = True

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
    Info2.questions {
        max-height: 24;
        padding: 1 0 0 0;
    }
    Info2 Tree {
        height: auto;
        background: transparent;
    }
    """

    ROLE_STYLES = {
        "system": "#d2a8ff",
        "tool def": "#56d4dd",
        "user": "#7ee787",
        "assistant": "#58a6ff",
        "tool": "#ffa657",
    }

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

    class SessionSelected(Message):
        """A session was selected inline."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class Dismissed(Message):
        """Panel was dismissed without selection."""

    class ApprovalResponse(Message):
        """User responded to an approval prompt."""

        def __init__(self, approved: bool, pattern: str | None) -> None:
            super().__init__()
            self.approved = approved
            self.pattern = pattern

    # ── Init ───────────────────────────────────────────────────────────

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode: Info2Mode = Info2Mode.HIDDEN
        self._items: list[Completion] = []
        self._model_items: list[dict] = []
        self._agent_items: list = []  # list[AgentProfile]
        self._session_items: list[dict] = []
        self._current_marker: str = ""
        self._prefix: str = "/"
        self._context_tree: Tree[str] | None = None
        self._approval_tool: str = ""
        self._approval_args: str = ""
        self._approval_pattern: str = ""
        self._approval_future: asyncio.Future | None = None
        self._questions_panel: QuestionsPanel | None = None

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

    def show_sessions(self, sessions: list[dict]) -> None:
        """Show inline session picker."""
        if not sessions:
            return
        self._mode = Info2Mode.SESSIONS
        self._session_items = sessions[:20]
        self.selected_index = 0
        self._rebuild_sessions()
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

    def show_approval(self, tool_name: str, args_summary: str, pattern: str) -> None:
        """Show a tool approval prompt in the panel."""
        if self._approval_future and not self._approval_future.done():
            self._approval_future.cancel()
        self._mode = Info2Mode.APPROVAL
        self._approval_tool = tool_name
        self._approval_args = args_summary
        self._approval_pattern = pattern
        self._approval_future = asyncio.get_event_loop().create_future()
        self.selected_index = 0
        self._rebuild_approval()
        self.add_class("active")
        self.call_after_refresh(self.focus)

    def show_questions(self, specs: list[QuestionSpec]) -> QuestionsPanel:
        """Mount a question panel inside info2 and return it."""
        self._mode = Info2Mode.QUESTIONS
        self.remove_children()
        panel = QuestionsPanel(specs)
        self._questions_panel = panel
        self.mount(panel)
        self.add_class("active")
        self.add_class("questions")
        return panel

    async def wait_for_approval(self) -> ApprovalResult:
        """Await the user's approval decision."""
        if self._approval_future is None:
            return ApprovalResult(False)
        return await self._approval_future

    def hide(self) -> None:
        """Hide the panel."""
        if self._approval_future and not self._approval_future.done():
            self._approval_future.set_result(ApprovalResult(False))
        self._mode = Info2Mode.HIDDEN
        self._items = []
        self._model_items = []
        self._agent_items = []
        self._session_items = []
        self._context_tree = None
        self._questions_panel = None
        self.remove_children()
        self.remove_class("active")
        self.remove_class("questions")

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
            case Info2Mode.SESSIONS:
                if (
                    self._session_items
                    and 0 <= self.selected_index < len(self._session_items)
                ):
                    return str(self._session_items[self.selected_index]["session_id"])
            case Info2Mode.CONTEXT:
                return None
            case Info2Mode.APPROVAL:
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
            case Info2Mode.SESSIONS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.SessionSelected(value))
                self.hide()
            case Info2Mode.CONTEXT:
                if self._context_tree is not None:
                    self._context_tree.action_toggle_node()
            case Info2Mode.APPROVAL:
                fut = self._approval_future
                idx = self.selected_index
                self._approval_future = None
                self.hide()
                if fut and not fut.done():
                    if idx == 0:
                        fut.set_result(ApprovalResult(True))
                    elif idx == 1:
                        fut.set_result(ApprovalResult(True, pattern=self._approval_pattern))
                    elif idx == 2:
                        fut.set_result(ApprovalResult(True, tool_scope="project"))
                    elif idx == 3:
                        fut.set_result(ApprovalResult(True, tool_scope="global"))
                    else:
                        fut.set_result(ApprovalResult(False))

    def dismiss(self) -> None:
        """Dismiss without selection."""
        fut = self._approval_future
        self._approval_future = None
        self.hide()
        if fut and not fut.done():
            fut.set_result(ApprovalResult(False))
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
            case Info2Mode.SESSIONS:
                return len(self._session_items)
            case Info2Mode.CONTEXT:
                return 0
            case Info2Mode.APPROVAL:
                return 5
            case Info2Mode.QUESTIONS:
                return 0
        return 0

    def _rebuild_completions(self) -> None:
        self.remove_children()
        for i, (name, desc, _) in enumerate(self._items):
            text = Text()
            text.append(f"{self._prefix}{name}", style="bold")
            if desc:
                text.append(f"  {desc}", style="dim")
            item = Info2Item(text)
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

    def _rebuild_sessions(self) -> None:
        self.remove_children()
        for i, session in enumerate(self._session_items):
            item = Info2Item(self._session_label(session))
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

        current_user = None
        current_reply = None
        user_count = 0
        for message in messages:
            role = str(getattr(message, "role", "unknown") or "unknown")
            content = self._message_content(message)
            if role == "system":
                system_content, tool_def_content = self._split_system_tool_def(content)
                if system_content:
                    system_tokens = self._estimate_text_tokens("system", system_content)
                    system_node = tree.root.add(
                        self._context_message_label("system", system_tokens, user_count),
                        expand=False,
                    )
                    self._add_context_message_details(system_node, message, system_content)
                if tool_def_content:
                    tool_def_tokens = self._estimate_text_tokens("tool def", tool_def_content)
                    tool_def_node = tree.root.add(
                        self._context_message_label(
                            "tool def", tool_def_tokens, user_count
                        ),
                        expand=False,
                    )
                    self._add_context_message_details(tool_def_node, message, tool_def_content)
                continue
            if role == "user":
                user_count += 1
            message_tokens = estimate_message_tokens(message)
            label = self._context_message_label(role, message_tokens, user_count)
            if role == "user":
                current_user = tree.root.add(label, expand=False)
                current_reply = None
                self._add_context_message_details(
                    current_user, message, content
                )
                continue
            if role == "assistant":
                parent = current_user or tree.root
                current_reply = parent.add(label, expand=False)
                self._add_context_message_details(
                    current_reply, message, content
                )
                continue
            if role == "tool":
                parent = current_reply or current_user or tree.root
            else:
                parent = tree.root
            group = parent.add(label, expand=False)
            self._add_context_message_details(group, message, content)
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
    def _session_label(session: dict) -> Text:
        sid = str(session.get("session_id", ""))
        desc = str(
            session.get("description") or _fallback_session_name(session)
        )[:40]
        mode = str(session.get("mode", "normal"))
        msgs = int(session.get("message_count", 0) or 0)
        ago = _time_ago(float(session.get("last_active", 0) or 0))
        mode_tag = " [ext]" if mode == "extensions" else ""
        text = Text()
        text.append(sid, style="bold cyan")
        text.append(f"  {desc:<40s}  ", style="white")
        text.append(f"{msgs:>3} msgs  {ago}{mode_tag}", style="dim")
        return text

    @staticmethod
    def _message_content(message: Any) -> str:
        content = getattr(message, "content", None) or ""
        if not content and getattr(message, "tool_calls", None):
            names = [
                str(getattr(call, "name", "tool"))
                for call in (getattr(message, "tool_calls", None) or [])
            ]
            content = "tool calls: " + ", ".join(names)
        if not content and getattr(message, "name", None):
            content = str(getattr(message, "name"))
        return str(content) or "(empty)"

    @staticmethod
    def _split_system_tool_def(content: str) -> tuple[str, str]:
        marker = "# Available tools"
        start = content.find(marker)
        if start < 0:
            return content, ""
        next_header = content.find("\n# ", start + len(marker))
        if next_header < 0:
            system_content = content[:start].rstrip()
            tool_def_content = content[start:].strip()
        else:
            system_content = (content[:start] + content[next_header:]).strip()
            tool_def_content = content[start:next_header].strip()
        return system_content, tool_def_content

    @staticmethod
    def _estimate_text_tokens(role: str, content: str) -> int:
        return max(1, (len(role) + len(content)) // 4 + 1)

    @staticmethod
    def _context_message_label(
        role: str,
        message_tokens: int,
        user_count: int,
    ) -> Text:
        text = Text()
        if role == "user":
            text.append(f"user {user_count}", style=f"bold {Info2.ROLE_STYLES['user']}")
        else:
            text.append(role, style=f"bold {Info2.ROLE_STYLES.get(role, '#c9d1d9')}")
        text.append(f"  {message_tokens:,}t", style="italic dim")
        return text

    @staticmethod
    def _add_context_message_details(
        node: Any,
        message: Any,
        content: str,
    ) -> None:
        content_node = node.add(Text("content", style="dim"), expand=True)
        for line in content.splitlines() or [content]:
            content_node.add_leaf(Text(line if line else " ", style="#c9d1d9"))
        if getattr(message, "name", None):
            node.add_leaf(Text(f"name: {getattr(message, 'name')}", style="dim"))
        if getattr(message, "tool_call_id", None):
            node.add_leaf(
                Text(f"tool_call_id: {getattr(message, 'tool_call_id')}", style="dim")
            )
        for call in getattr(message, "tool_calls", None) or []:
            name = str(getattr(call, "name", "tool"))
            call_id = str(getattr(call, "call_id", ""))
            node.add_leaf(
                Text(f"tool_call: {name} {call_id}".rstrip(), style="#ffa657")
            )

    def _rebuild_approval(self) -> None:
        self.remove_children()
        header = Static(f"Allow {self._approval_tool}({self._approval_args})?")
        self.mount(header)
        options = [
            "  Allow",
            f"  Allow all '{self._approval_pattern}' for this session",
            f"  Allow all {self._approval_tool} commands (project extension)",
            f"  Allow all {self._approval_tool} commands (global extension)",
            "  Deny",
        ]
        for i, label in enumerate(options):
            item = Info2Item(label)
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

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


def _fallback_session_name(session: dict) -> str:
    """Label for sessions that never called session_name — their created time."""
    ts = float(session.get("created_at", 0) or 0)
    if ts <= 0:
        return "(unnamed)"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _time_ago(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"
