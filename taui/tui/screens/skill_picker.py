"""Skill picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from taui.skills import Skill


class SkillPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a skill."""

    DEFAULT_CSS = """
    SkillPickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #skill-picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: #0d0d0d;
        border: none;
        padding: 0;
    }
    #skill-picker-dialog #skill-search {
        width: 100%;
        background: #121212;
        border: solid #2a2a2a;
    }
    #skill-picker-dialog #skill-search:focus {
        border: solid #5a5a5a;
    }
    #skill-picker-dialog OptionList {
        height: 18;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #skill-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #skill-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    """

    def __init__(self, skills: list[Skill]) -> None:
        super().__init__()
        self._skills = skills[:50]

    def compose(self) -> ComposeResult:
        with Container(id="skill-picker-dialog"):
            yield Input(placeholder="Search skills…", id="skill-search")
            yield OptionList(
                *[
                    Option(_skill_prompt(skill), id=skill.name)
                    for skill in self._skills
                ],
                id="skill-options",
            )


    def on_mount(self) -> None:
        self.query_one("#skill-search", Input).focus()

    def _filter(self, query: str) -> list[Skill]:
        q = query.lower().strip()
        if not q:
            return list(self._skills)
        substring = [s for s in self._skills if q in s.name.lower()]
        seen = {s.name for s in substring}
        subseq = [
            s for s in self._skills
            if s.name not in seen and _subseq_match(q, s.name.lower())
        ]
        return substring + subseq

    @on(Input.Changed, "#skill-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#skill-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        for skill in self._filter(event.value):
            opts.add_option(Option(_skill_prompt(skill), id=skill.name))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#skill-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#skill-options", OptionList)
        except Exception:
            return
        if opts.option_count == 0:
            return
        idx = opts.highlighted or 0
        opt = opts.get_option_at_index(idx)
        self.dismiss(opt.id)

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            option_id = self._skills[event.option_index].name
        self.dismiss(str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _subseq_match(query: str, target: str) -> bool:
    """Return True if every char in `query` appears in `target` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)


def _skill_prompt(skill: Skill) -> Text:
    marker = " ◀" if skill.loaded else ""
    text = Text()
    text.append(f"{skill.name:<30s}", style="bold" if skill.loaded else "white")
    text.append(f"  {skill.scope}{marker}", style="dim")
    return text
