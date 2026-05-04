"""Question panel widget — one-at-a-time with < > navigation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option


@dataclass(slots=True)
class QuestionSpec:
    """One question with optional pre-defined choices."""

    question: str
    options: list[str] | None = None


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
        ) -> None:
            super().__init__()
            self.option_list = option_list
            self.key = key
            self.character = character

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
                self._custom_active = False
                event.stop()
                event.prevent_default()
                self.action_select()
            return
        if event.character or event.key in {"backspace", "delete"}:
            if not self._custom_active:
                self._custom_active = True
            event.stop()
            event.prevent_default()
            self.post_message(self.CustomEdited(self, event.key, event.character))


class QuestionsPanel(Widget):
    """One question at a time, paginated with < > arrows.

    Layout per the wireframe:
        ┌──────────────────────────────────── 1/n  < > ─┐
        │  <question>                                    │
        │  ┌──────────────────────────────────────────┐  │
        │  │ 1. option A                              │  │
        │  │ 2. option B                              │  │
        │  │ 3. option C                              │  │
        │  │ 4. ░░░ custom input ░░░░░░░░░░░░░░░░░░░░ │  │
        │  └──────────────────────────────────────────┘  │
        └────────────────────────────────────────────────┘

    Single-question: auto-resolves on selection (no nav).
    Multi-question: nav with < >, auto-advance on answer.
    """

    DEFAULT_CSS = """
    QuestionsPanel {
        layout: vertical;
        height: auto;
        max-height: 22;
        background: $surface;
        padding: 1 1 0 1;
        margin: 0 2 1 2;
    }
    QuestionsPanel .qp-header {
        height: 1;
        align-horizontal: right;
        padding: 0 0;
    }
    QuestionsPanel .qp-indicator {
        width: auto;
        color: $text-muted;
        padding: 0 0 0 0;
    }
    QuestionsPanel .qp-nav-btn {
        min-width: 3;
        max-width: 3;
        height: 1;
        border: none;
        padding: 0;
        margin: 0;
        color: $text;
    }
    QuestionsPanel .qp-question {
        padding: 0 1;
        color: $text;
    }
    QuestionsPanel .qp-options-box {
        height: auto;
        margin: 1 0 0 0;
        background: $surface;
    }
    QuestionsPanel OptionList {
        height: auto;
        max-height: 18;
        margin: 0;
        padding: 0;
        background: $surface;
        border: none;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
    }
    QuestionsPanel OptionList:focus {
        border: none;
    }
    QuestionsPanel OptionList > .option-list--option {
        padding: 0 1;
    }
    QuestionsPanel OptionList > .option-list--option-highlighted {
        background: $accent 30%;
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

    # ── compose ──────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        multi = len(self._specs) > 1
        with Horizontal(classes="qp-header"):
            yield Label(
                self._indicator_text(),
                id="qp-ind",
                classes="qp-indicator",
            )
            if multi:
                yield Button(
                    "<", id="qp-prev", variant="default",
                    classes="qp-nav-btn", disabled=True,
                )
                yield Button(
                    ">", id="qp-next", variant="default",
                    classes="qp-nav-btn",
                    disabled=len(self._specs) <= 1,
                )
        for i, spec in enumerate(self._specs):
            cls = "" if i == 0 else "qp-hidden"
            with Vertical(id=f"qp-pane-{i}", classes=cls):
                yield Label(
                    f"{spec.question}",
                    classes="qp-question",
                    markup=True,
                )
                opts = spec.options or []
                entries = [
                    Option(self._option_prompt(j, o)) for j, o in enumerate(opts, 1)
                ]
                entries.append(
                    Option(
                        self._custom_prompt(i, len(opts)),
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

    # ── navigation ───────────────────────────────────────────

    def _indicator_text(self) -> str:
        return f"{self._current + 1}/{len(self._specs)}"

    def _sync_nav(self) -> None:
        try:
            self.query_one("#qp-ind", Label).update(self._indicator_text())
        except Exception:
            pass
        try:
            self.query_one("#qp-prev", Button).disabled = self._current == 0
        except Exception:
            pass
        try:
            self.query_one("#qp-next", Button).disabled = (
                self._current >= len(self._specs) - 1
            )
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "qp-prev":
            self._goto(self._current - 1)
        elif event.button.id == "qp-next":
            self._goto(self._current + 1)

    # ── answer handling ──────────────────────────────────────

    def _resolve(self) -> None:
        self.post_message(self.Confirmed(list(self._answers)))
        if self._future and not self._future.done():
            self._future.set_result(list(self._answers))

    def _option_prompt(self, option_number: int, label: str) -> Text:
        return Text(f"\n{option_number}. {label}\n")

    def _custom_prompt(self, question_index: int, option_count: int, active: bool = False) -> Text:
        value = self._custom_answers[question_index]
        prompt = Text(f"\n{option_count + 1}. ")
        if value:
            prompt.append(value)
        if active:
            prompt.append("▌")
        elif not value:
            prompt.append("custom", style="dim")
        prompt.append("\n")
        return prompt

    def on_question_option_list_custom_edited(
        self, event: QuestionOptionList.CustomEdited
    ) -> None:
        event.stop()
        i = self._current
        if event.key in {"backspace", "delete"}:
            self._custom_answers[i] = self._custom_answers[i][:-1]
        elif event.character:
            self._custom_answers[i] += event.character
        spec = self._specs[i]
        event.option_list.replace_option_prompt(
            f"qp-custom-{i}",
            self._custom_prompt(
                i,
                len(spec.options or []),
                active=event.option_list.is_custom_active,
            ),
        )

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        i = self._current
        spec = self._specs[i]
        opts = spec.options or []
        idx = event.option_index
        self._answers[i] = (
            opts[idx]
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
