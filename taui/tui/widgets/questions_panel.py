"""Question panel widget — one-at-a-time with Tab navigation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key, Paste
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

HIGHLIGHT_MARKER_STYLE = "bold #0178d4"
RECOMMENDED_STYLE = "italic #0178d4"
DETAIL_STYLE = "dim"


@dataclass(slots=True)
class QuestionOption:
    """A single answer option."""

    label: str
    description: str | None = None


@dataclass(slots=True)
class QuestionSpec:
    """One question with optional pre-defined choices.

    `options` accepts either a list of `QuestionOption` objects or a list of
    raw strings (each treated as a label with no description). `recommended`
    is the 1-based index of the preferred option, if any.
    """

    question: str
    options: list[QuestionOption] | list[str] | None = None
    recommended: int | None = None
    _normalized: list[QuestionOption] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.options is None:
            self._normalized = None
            return
        normalized: list[QuestionOption] = []
        for o in self.options:
            if isinstance(o, QuestionOption):
                normalized.append(o)
            elif isinstance(o, str):
                normalized.append(QuestionOption(label=o, description=None))
            elif isinstance(o, dict):
                lab = o.get("label", "")
                if not isinstance(lab, str):
                    continue
                desc = o.get("description")
                if desc is not None and not isinstance(desc, str):
                    desc = str(desc)
                normalized.append(QuestionOption(label=lab, description=desc))
        self._normalized = normalized or None

    @property
    def norm_options(self) -> list[QuestionOption]:
        """Return options as QuestionOption objects (empty list if None)."""
        return list(self._normalized) if self._normalized else []


class QuestionOptionList(OptionList):
    """OptionList with an inline-editable last (custom) option.

    First Enter on the custom row activates it (typing mode).
    Enter while active submits the option.
    Typing characters auto-activates.
    Navigating away deactivates.
    """

    class CustomEdited(Message):
        """Fires when the custom option text changes or active state changes."""

        def __init__(
            self,
            option_list: QuestionOptionList,
            key: str,
            character: str | None,
            paste_text: str | None = None,
        ) -> None:
            super().__init__()
            self.option_list = option_list
            self.key = key
            self.character = character
            self.paste_text = paste_text

    _custom_active: bool = False

    @property
    def custom_index(self) -> int:
        return len(self.options) - 1

    @property
    def is_custom_active(self) -> bool:
        return self._custom_active

    def deactivate(self) -> None:
        if self._custom_active:
            self._custom_active = False
            self.post_message(self.CustomEdited(self, "", None))

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_index != self.custom_index:
            self.deactivate()

    def on_key(self, event: Key) -> None:
        if self.highlighted != self.custom_index:
            return
        if event.key == "enter":
            if not self._custom_active:
                self._custom_active = True
                event.stop()
                event.prevent_default()
                self.post_message(self.CustomEdited(self, "", None))
            else:
                event.stop()
                event.prevent_default()
                # Keep _custom_active=True through action_select so the
                # panel can tell a real submission from a stray click that
                # only highlighted the row.
                self.action_select()
            return
        if event.character or event.key in {"backspace", "delete"}:
            if not self._custom_active:
                self._custom_active = True
            event.stop()
            event.prevent_default()
            self.post_message(self.CustomEdited(self, event.key, event.character))

    def activate(self) -> None:
        """Programmatically enter typing mode for the custom row."""
        if not self._custom_active:
            self._custom_active = True
            self.post_message(self.CustomEdited(self, "", None))

    async def _on_paste(self, event: Paste) -> None:
        """Append pasted text to the custom answer when the row is focused."""
        if self.highlighted != self.custom_index:
            return
        text = event.text
        if not text:
            return
        # Strip newlines — the custom row is a single-line field.
        cleaned = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        if not cleaned:
            return
        if not self._custom_active:
            self._custom_active = True
        event.stop()
        event.prevent_default()
        self.post_message(self.CustomEdited(self, "", None, paste_text=cleaned))



class QuestionsPanel(Widget):
    """One question at a time, paginated with Tab.

    Layout per the wireframe:
        ┌────────────────────────────────────────── 1/n ─┐
        │  <question>                                    │
        │  ┌──────────────────────────────────────────┐  │
        │  │ 1. option A (recommended)    detail text │  │
        │  │ 2. option B                  detail text │  │
        │  │ 3. option C                              │  │
        │  │ 4. ░░░ custom input ░░░░░░░░░░░░░░░░░░░░ │  │
        │  └──────────────────────────────────────────┘  │
        └────────────────────────────────────────────────┘

    Single-question: auto-resolves on selection (no nav).
    Multi-question: nav with Tab, auto-advance on answer.
    """

    DEFAULT_CSS = """
    QuestionsPanel {
        layout: vertical;
        height: auto;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    QuestionsPanel .qp-question-row {
        height: 1;
        padding: 0;
        margin: 0 0 1 0;
    }
    QuestionsPanel .qp-indicator {
        width: auto;
        color: $text-muted;
        padding: 0 2 0 0;
    }
    QuestionsPanel .qp-question {
        width: 1fr;
        padding: 0 2;
        color: $text;
        text-style: bold;
    }
    QuestionsPanel .qp-pane {
        height: auto;
    }
    QuestionsPanel .qp-options-box {
        height: auto;
        margin: 0;
        background: transparent;
    }
    QuestionsPanel OptionList {
        height: auto;
        margin: 0;
        padding: 0 1;
        background: transparent;
        border: none;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
    }
    QuestionsPanel OptionList:focus {
        border: none;
    }
    QuestionsPanel OptionList > .option-list--option {
        padding: 0 2;
        color: $text-muted;
    }
    QuestionsPanel OptionList > .option-list--option-highlighted {
        color: $text;
        background: $surface-lighten-1;
        text-style: bold;
    }
    QuestionsPanel OptionList:focus > .option-list--option-highlighted {
        color: $text;
        background: $surface-lighten-1;
        text-style: bold;
    }
    QuestionsPanel .qp-hidden {
        display: none;
    }
    """

    class Confirmed(Message):
        def __init__(self, answers: list[str | None]) -> None:
            super().__init__()
            self.answers = answers

    def __init__(self, specs: list[QuestionSpec]) -> None:
        super().__init__()
        self._specs = specs
        self._answers: list[str | None] = [None] * len(specs)
        self._answered: set[int] = set()
        self._custom_answers: list[str] = [""] * len(specs)
        self._current = 0
        self._future: asyncio.Future[list[str | None]] | None = None
        # Cached usable width for trailing-detail layout; updated on resize.
        self._content_width: int = 0

    # ── compose ──────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        for i, spec in enumerate(self._specs):
            cls = "qp-pane" if i == 0 else "qp-pane qp-hidden"
            with Vertical(id=f"qp-pane-{i}", classes=cls):
                with Horizontal(classes="qp-question-row"):
                    yield Label(
                        f"{spec.question}",
                        classes="qp-question",
                        markup=True,
                    )
                    yield Label(
                        self._indicator_text(i),
                        id=f"qp-ind-{i}",
                        classes="qp-indicator",
                    )
                opts = spec.norm_options
                entries = [
                    Option(
                        self._option_prompt(i, j, o, highlighted=j == 1),
                        id=f"qp-opt-{i}-{j - 1}",
                    )
                    for j, o in enumerate(opts, 1)
                ]
                entries.append(
                    Option(
                        self._custom_prompt(i, len(opts), highlighted=not opts),
                        id=f"qp-custom-{i}",
                    )
                )
                with Vertical(classes="qp-options-box"):
                    yield QuestionOptionList(
                        *entries,
                        id=f"qp-opts-{i}",
                    )

    def on_mount(self) -> None:
        self._focus_current()

    def on_resize(self, event: Any) -> None:  # pragma: no cover - layout hook
        # Re-render rows so detail text right-aligns to the new width.
        try:
            self._content_width = self.size.width
        except Exception:
            self._content_width = 0
        for i, spec in enumerate(self._specs):
            try:
                ol = self.query_one(f"#qp-opts-{i}", QuestionOptionList)
            except Exception:
                continue
            opts = spec.norm_options
            highlighted = ol.highlighted
            for j, opt in enumerate(opts, 1):
                ol.replace_option_prompt(
                    f"qp-opt-{i}-{j - 1}",
                    self._option_prompt(
                        i, j, opt, highlighted=highlighted == j - 1
                    ),
                )

    # ── navigation ───────────────────────────────────────────

    def _indicator_text(self, index: int | None = None) -> str:
        idx = self._current if index is None else index
        return f"{idx + 1}/{len(self._specs)}"

    def _sync_nav(self) -> None:
        for i in range(len(self._specs)):
            try:
                self.query_one(f"#qp-ind-{i}", Label).update(self._indicator_text(i))
            except Exception:
                pass

    def _goto(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._specs):
            return
        # Deactivate custom on the question we're leaving
        try:
            self.query_one(f"#qp-opts-{self._current}", QuestionOptionList).deactivate()
        except Exception:
            pass
        for i in range(len(self._specs)):
            try:
                pane = self.query_one(f"#qp-pane-{i}", Vertical)
                if i == idx:
                    pane.remove_class("qp-hidden")
                else:
                    pane.add_class("qp-hidden")
            except Exception:
                pass
        self._current = idx
        self._sync_nav()
        self._focus_current()

    def _focus_current(self) -> None:
        try:
            self.query_one(
                f"#qp-opts-{self._current}", QuestionOptionList
            ).focus()
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        if len(self._specs) <= 1:
            return
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self._goto(min(self._current + 1, len(self._specs) - 1))
        elif event.key == "shift+tab":
            event.stop()
            event.prevent_default()
            self._goto(self._current - 1)

    # ── answer handling ──────────────────────────────────────

    def _resolve(self) -> None:
        self.post_message(self.Confirmed(list(self._answers)))
        if self._future and not self._future.done():
            self._future.set_result(list(self._answers))

    def _row_width(self) -> int:
        """Best-effort interior width used to right-align detail text."""
        w = self._content_width or 0
        if not w:
            try:
                w = self.size.width
            except Exception:
                w = 0
        # Account for the OptionList padding (0 1) and our prefix/indent.
        return max(0, w - 8)

    def _option_prompt(
        self,
        question_index: int,
        option_number: int,
        option: QuestionOption,
        highlighted: bool = False,
    ) -> Text:
        prefix = Text("┃ ", style=HIGHLIGHT_MARKER_STYLE) if highlighted else Text("  ")
        body = Text(f"{option_number}. ") + Text(option.label)
        spec = self._specs[question_index]
        if spec.recommended == option_number:
            body.append(" ")
            body.append("(recommended)", style=RECOMMENDED_STYLE)
        line = Text("\n") + prefix + body
        if option.description:
            available = self._row_width() - line.cell_len
            detail = f"  {option.description}"
            if available > 4:
                if len(detail) > available:
                    detail = detail[: max(0, available - 1)] + "…"
                pad = max(1, available - len(detail))
                line.append(" " * pad)
                line.append(detail.lstrip(" "), style=DETAIL_STYLE)
            else:
                line.append("  ")
                line.append(option.description, style=DETAIL_STYLE)
        line.append("\n")
        return line

    def _custom_prompt(
        self,
        question_index: int,
        option_count: int,
        active: bool = False,
        highlighted: bool = False,
    ) -> Text:
        value = self._custom_answers[question_index]
        prefix = Text("┃ ", style=HIGHLIGHT_MARKER_STYLE) if highlighted else Text("  ")
        prompt = Text("\n") + prefix + Text(f"{option_count + 1}. ")
        if value:
            prompt.append(value)
        if active:
            prompt.append("▌")
        elif not value:
            prompt.append("custom", style="dim")
        prompt.append("\n")
        return prompt

    def _question_index_for_option_list(self, option_list: OptionList) -> int | None:
        if not option_list.id or not option_list.id.startswith("qp-opts-"):
            return None
        try:
            return int(option_list.id.removeprefix("qp-opts-"))
        except ValueError:
            return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        ol = event.option_list
        i = self._question_index_for_option_list(ol)
        if i is None:
            return
        spec = self._specs[i]
        opts = spec.norm_options
        for j, opt in enumerate(opts, 1):
            ol.replace_option_prompt(
                f"qp-opt-{i}-{j - 1}",
                self._option_prompt(
                    i,
                    j,
                    opt,
                    highlighted=event.option_index == j - 1,
                ),
            )
        custom_idx = len(opts)
        ol.replace_option_prompt(
            f"qp-custom-{i}",
            self._custom_prompt(
                i,
                len(opts),
                active=isinstance(ol, QuestionOptionList) and ol.is_custom_active,
                highlighted=event.option_index == custom_idx,
            ),
        )

    def on_question_option_list_custom_edited(
        self, event: QuestionOptionList.CustomEdited
    ) -> None:
        event.stop()
        i = self._current
        if event.paste_text:
            self._custom_answers[i] += event.paste_text
        elif event.key in {"backspace", "delete"}:
            self._custom_answers[i] = self._custom_answers[i][:-1]
        elif event.character:
            self._custom_answers[i] += event.character
        spec = self._specs[i]
        event.option_list.replace_option_prompt(
            f"qp-custom-{i}",
            self._custom_prompt(
                i,
                len(spec.norm_options),
                active=event.option_list.is_custom_active,
                highlighted=(
                    event.option_list.highlighted == event.option_list.custom_index
                ),
            ),
        )

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        i = self._current
        spec = self._specs[i]
        opts = spec.norm_options
        idx = event.option_index
        ol = getattr(event, "option_list", None)
        # If the user clicked (or pressed Enter on) the custom row but
        # hasn't entered typing mode yet, focus the row for editing
        # instead of submitting an empty answer. Enter while already
        # active falls through to the normal resolve path.
        if (
            idx == len(opts)
            and isinstance(ol, QuestionOptionList)
            and not ol.is_custom_active
        ):
            event.stop()
            ol.activate()
            ol.replace_option_prompt(
                f"qp-custom-{i}",
                self._custom_prompt(
                    i,
                    len(opts),
                    active=True,
                    highlighted=True,
                ),
            )
            return
        if idx == len(opts) and isinstance(ol, QuestionOptionList):
            # Leaving editing mode for a real selection.
            ol._custom_active = False
        self._answers[i] = (
            opts[idx].label
            if idx < len(opts)
            else self._custom_answers[i].strip() or None
        )
        self._advance_or_resolve()

    def _advance_or_resolve(self) -> None:
        self._answered.add(self._current)
        if len(self._specs) == 1:
            self._resolve()
            return
        if len(self._answered) == len(self._specs):
            self._resolve()
            return
        nxt = self._current + 1
        if nxt < len(self._specs):
            self._goto(nxt)

    def on_unmount(self) -> None:
        if self._future and not self._future.done():
            self._future.cancel()

    async def wait_for_answers(self) -> list[str | None]:
        """Block until the user confirms all answers."""
        loop = asyncio.get_running_loop()
        self._future = loop.create_future()
        return await self._future
