"""Info2 – unified expandable panel above the chat input.

Modes:
- completions: slash-command autocomplete list
- models: inline model picker
- agents: inline agent picker
- context: inline context tree
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Tree

from taui.tui.widgets.context_tree import ROLE_STYLES, build_context_tree
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec

type Completion = tuple[str, str, bool]  # (name, description, accepts_args)

# Display labels for model-variant (reasoning effort) ids; mirrors the
# standalone variant picker screen.
_VARIANT_LABELS: dict[str, str] = {
    "none": "None",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra-high",
    "max": "Max",
}


@dataclass(slots=True)
class ApprovalResult:
    """Result from an approval prompt."""

    approved: bool
    # True when the user chose "Allow for session" — the caller then allowlists
    # this tool for the rest of the session (not just this one call).
    allow_session: bool = False


class Info2Mode(Enum):
    HIDDEN = auto()
    COMPLETIONS = auto()
    MODELS = auto()
    VARIANTS = auto()
    AGENTS = auto()
    SKILLS = auto()
    PROMPTS = auto()
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
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 8;
        display: none;
        scrollbar-size: 1 1;
        padding: 0 0 0 1;
        margin: 0 2 6 2;
        max-width: 100%;
        background: $surface;
        border: none;
        border-right: none;
        border-left: none;
    }
    Info2.active {
        display: block;
        border-top: tall $primary;
        border-bottom: tall $primary;
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

    ROLE_STYLES = ROLE_STYLES

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

    class VariantSelected(Message):
        """A model variant (reasoning effort) was selected inline."""

        def __init__(self, variant: str) -> None:
            super().__init__()
            self.variant = variant

    class AgentSelected(Message):
        """An agent was selected inline."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    class SkillSelected(Message):
        """A skill was selected inline."""

        def __init__(self, skill_name: str) -> None:
            super().__init__()
            self.skill_name = skill_name

    class PromptSelected(Message):
        """A prompt was selected inline."""

        def __init__(self, prompt_id: str) -> None:
            super().__init__()
            self.prompt_id = prompt_id

    class Dismissed(Message):
        """Panel was dismissed without selection."""

    class ApprovalResponse(Message):
        """User responded to an approval prompt."""

        def __init__(self, approved: bool) -> None:
            super().__init__()
            self.approved = approved

    # ── Init ───────────────────────────────────────────────────────────

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode: Info2Mode = Info2Mode.HIDDEN
        self._items: list[Completion] = []
        self._model_items: list[dict] = []
        # Each entry is (value, label); the leading "" entry clears the variant.
        self._variant_items: list[tuple[str, str]] = []
        self._agent_items: list = []  # list[AgentProfile]
        self._skill_items: list = []  # list[Skill]
        self._prompt_items: list = []  # list[Item]
        self._current_marker: str = ""
        self._prefix: str = "/"
        self._context_tree: Tree[str] | None = None
        self._approval_tool: str = ""
        self._approval_args: str = ""
        self._approval_future: asyncio.Future | None = None
        self._questions_panel: QuestionsPanel | None = None
        # Fuzzy-search filter state for inline pickers (models/agents). The
        # ``_all`` lists hold the unfiltered source; ``_filter_query`` is the
        # current search string; the per-mode ``_items`` lists hold the
        # filtered view that's actually rendered.
        self._models_all: list[dict] = []
        self._agents_all: list = []
        self._filter_query: str = ""

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
        self._models_all = list(models)
        self._filter_query = ""
        self._model_items = self._models_all[:50]
        self._current_marker = current
        self.selected_index = 0
        # Try to pre-select current model
        for i, m in enumerate(self._model_items):
            if str(m.get("id", "")) == current:
                self.selected_index = i
                break
        self._rebuild_models()
        self.add_class("active")

    def show_variants(self, variants: list[str], current: str) -> None:
        """Show inline model-variant (reasoning effort) picker.

        Always leads with a "(default)" entry that clears the variant.
        """
        self._mode = Info2Mode.VARIANTS
        entries: list[tuple[str, str]] = [("", "(default — no variant)")]
        for v in variants:
            entries.append((v, _VARIANT_LABELS.get(v, v.title())))
        self._variant_items = entries
        self._current_marker = current
        self.selected_index = 0
        for i, (key, _) in enumerate(entries):
            if key == current:
                self.selected_index = i
                break
        self._rebuild_variants()
        self.add_class("active")

    def show_agents(self, agents: list, current: str) -> None:
        """Show inline agent picker."""
        if not agents:
            return
        self._mode = Info2Mode.AGENTS
        self._agents_all = list(agents)
        self._filter_query = ""
        self._agent_items = self._agents_all[:50]
        self._current_marker = current.upper()
        self.selected_index = 0
        for i, a in enumerate(self._agent_items):
            if a.id.upper() == self._current_marker:
                self.selected_index = i
                break
        self._rebuild_agents()
        self.add_class("active")

    def show_skills(self, skills: list) -> None:
        """Show inline skill picker."""
        if not skills:
            return
        self._mode = Info2Mode.SKILLS
        self._skill_items = skills[:50]
        self.selected_index = 0
        self._rebuild_skills()
        self.add_class("active")

    def show_prompts(self, prompts: list) -> None:
        """Show inline prompt picker."""
        if not prompts:
            return
        self._mode = Info2Mode.PROMPTS
        self._prompt_items = prompts[:50]
        self.selected_index = 0
        self._rebuild_prompts()
        self.add_class("active")

    def show_context_tree(self, messages: list[Any], max_tokens: int) -> None:
        """Show an inline context tree grouped by message role."""
        self._mode = Info2Mode.CONTEXT
        self._context_tree = build_context_tree(messages, max_tokens)
        self.selected_index = 0
        self.remove_children()
        self.mount(self._context_tree)
        self.call_after_refresh(self._context_tree.focus)
        self.add_class("active")

    def show_approval(self, tool_name: str, args_summary: str) -> None:
        """Show a tool approval prompt in the panel."""
        if self._approval_future and not self._approval_future.done():
            self._approval_future.cancel()
        self._mode = Info2Mode.APPROVAL
        self._approval_tool = tool_name
        self._approval_args = args_summary
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
        self._variant_items = []
        self._agent_items = []
        self._skill_items = []
        self._prompt_items = []
        self._models_all = []
        self._agents_all = []
        self._filter_query = ""
        self._context_tree = None
        self._questions_panel = None
        self.remove_children()
        self.remove_class("active")
        self.remove_class("questions")

    # ── Filter (used by inline model/agent picker fuzzy search) ────────

    @property
    def supports_filter(self) -> bool:
        return self._mode in (Info2Mode.MODELS, Info2Mode.AGENTS)

    @property
    def filter_query(self) -> str:
        return self._filter_query

    def append_filter_char(self, ch: str) -> None:
        if not self.supports_filter or len(ch) != 1:
            return
        self._filter_query += ch
        self._apply_filter()

    def pop_filter_char(self) -> None:
        if not self.supports_filter or not self._filter_query:
            return
        self._filter_query = self._filter_query[:-1]
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._filter_query.lower().strip()
        if self._mode == Info2Mode.MODELS:
            self._model_items = _rank_by_query(
                self._models_all,
                query,
                key=lambda m: str(m.get("id", "")).lower(),
            )[:50]
            self.selected_index = 0
            self._rebuild_models()
        elif self._mode == Info2Mode.AGENTS:
            self._agent_items = _rank_by_query(
                self._agents_all,
                query,
                key=lambda a: f"{a.id} {a.name}".lower(),
            )[:50]
            self.selected_index = 0
            self._rebuild_agents()

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
            case Info2Mode.VARIANTS:
                if self._variant_items and 0 <= self.selected_index < len(self._variant_items):
                    return self._variant_items[self.selected_index][0]
            case Info2Mode.AGENTS:
                if self._agent_items and 0 <= self.selected_index < len(self._agent_items):
                    return self._agent_items[self.selected_index].id
            case Info2Mode.SKILLS:
                if self._skill_items and 0 <= self.selected_index < len(self._skill_items):
                    return self._skill_items[self.selected_index].name
            case Info2Mode.PROMPTS:
                if self._prompt_items and 0 <= self.selected_index < len(self._prompt_items):
                    item = self._prompt_items[self.selected_index]
                    return getattr(item, "identifier", None) or item.get("identifier")
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
            case Info2Mode.VARIANTS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.VariantSelected(value))
                self.hide()
            case Info2Mode.AGENTS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.AgentSelected(value))
                self.hide()
            case Info2Mode.SKILLS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.SkillSelected(value))
                self.hide()
            case Info2Mode.PROMPTS:
                value = self.current_value
                if value is not None:
                    self.post_message(self.PromptSelected(value))
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
                    # idx: 0 = allow once, 1 = allow for session, 2 = deny
                    fut.set_result(
                        ApprovalResult(
                            approved=idx in (0, 1),
                            allow_session=idx == 1,
                        )
                    )

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
            case Info2Mode.VARIANTS:
                return len(self._variant_items)
            case Info2Mode.AGENTS:
                return len(self._agent_items)
            case Info2Mode.SKILLS:
                return len(self._skill_items)
            case Info2Mode.PROMPTS:
                return len(self._prompt_items)
            case Info2Mode.CONTEXT:
                return 0
            case Info2Mode.APPROVAL:
                return 3
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
        self._mount_filter_header()
        for i, model in enumerate(self._model_items):
            item = Info2Item(self._model_label(model))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _rebuild_variants(self) -> None:
        self.remove_children()
        for i, (key, label) in enumerate(self._variant_items):
            item = Info2Item(self._variant_label(key, label))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _rebuild_agents(self) -> None:
        self.remove_children()
        self._mount_filter_header()
        for i, agent in enumerate(self._agent_items):
            item = Info2Item(self._agent_label(agent))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _mount_filter_header(self) -> None:
        if not self._filter_query:
            return
        header = Static(
            Text.assemble(
                ("> ", "dim"),
                (self._filter_query, "bold cyan"),
            )
        )
        self.mount(header)

    def _rebuild_skills(self) -> None:
        self.remove_children()
        for i, skill in enumerate(self._skill_items):
            item = Info2Item(self._skill_label(skill))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

    def _rebuild_prompts(self) -> None:
        self.remove_children()
        for i, prompt in enumerate(self._prompt_items):
            item = Info2Item(self._prompt_label(prompt))
            if i == self.selected_index:
                item.add_class("highlighted")
            self.mount(item)

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

    def _variant_label(self, key: str, label: str) -> Text:
        marker = " ◀" if key == self._current_marker else ""
        text = Text()
        text.append(f"{label:<24s}", style="bold cyan" if marker else "white")
        text.append(marker, style="bold cyan")
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
    def _skill_label(skill) -> Text:
        marker = " ◀" if skill.loaded else ""
        text = Text()
        text.append(
            f"{skill.name:<30s}",
            style="bold cyan" if marker else "white",
        )
        text.append(f"  {skill.scope}{marker}", style="dim")
        return text

    @staticmethod
    def _prompt_label(prompt) -> Text:
        label = getattr(prompt, "label", "") or prompt.get("label", "")
        summary = getattr(prompt, "summary", "") or prompt.get("summary", "")
        scope = getattr(prompt, "scope", "") or prompt.get("scope", "")
        text = Text()
        text.append(f"{label:<20s}", style="white")
        text.append(f"  {summary[:40]:<40s}", style="dim")
        text.append(f"  {scope}", style="dim")
        return text

    def _rebuild_approval(self) -> None:
        self.remove_children()
        header = Static(
            f"Allow {self._approval_tool}({self._approval_args})?", markup=False
        )
        self.mount(header)
        for i, label in enumerate(
            ("  Allow once", "  Allow for session", "  Deny")
        ):
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


def _rank_by_query(items, query: str, key) -> list:
    """Substring matches first, then subsequence matches. Empty query → all."""
    if not query:
        return list(items)
    substring: list = []
    subseq: list = []
    for item in items:
        target = key(item)
        if query in target:
            substring.append(item)
        elif _subseq_match(query, target):
            subseq.append(item)
    return substring + subseq


def _subseq_match(query: str, target: str) -> bool:
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)

