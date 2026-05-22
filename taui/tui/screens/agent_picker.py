"""Agent picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from taui.self_edit import AgentProfile


class AgentPickerScreen(ModalScreen[str | None]):
    """Modal for selecting an agent profile."""

    DEFAULT_CSS = """
    AgentPickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #agent-picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: #0d0d0d;
        border: none;
        padding: 0;
    }
    #agent-picker-dialog #agent-search {
        width: 100%;
        background: #121212;
        border: solid #2a2a2a;
    }
    #agent-picker-dialog #agent-search:focus {
        border: solid #5a5a5a;
    }
    #agent-picker-dialog OptionList {
        height: 18;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #agent-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #agent-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    """

    def __init__(self, agents: list[AgentProfile], *, current: str) -> None:
        super().__init__()
        self._agents = agents[:50]
        self._current = current.upper()

    def compose(self) -> ComposeResult:
        with Container(id="agent-picker-dialog"):
            yield Input(placeholder="Search agents…", id="agent-search")
            yield OptionList(
                *[
                    Option(_agent_prompt(agent, current=self._current), id=agent.id)
                    for agent in self._agents
                ],
                id="agent-options",
            )


    def on_mount(self) -> None:
        self.query_one("#agent-search", Input).focus()

    def _filter(self, query: str) -> list[AgentProfile]:
        q = query.lower().strip()
        if not q:
            return list(self._agents)
        substring = [
            a for a in self._agents
            if q in a.id.lower() or q in a.name.lower()
        ]
        seen_ids = {a.id for a in substring}
        subseq = [
            a for a in self._agents
            if a.id not in seen_ids
            and (_subseq_match(q, a.id.lower()) or _subseq_match(q, a.name.lower()))
        ]
        return substring + subseq

    @on(Input.Changed, "#agent-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#agent-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        for agent in self._filter(event.value):
            opts.add_option(Option(_agent_prompt(agent, current=self._current), id=agent.id))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#agent-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#agent-options", OptionList)
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
            option_id = self._agents[event.option_index].id
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


def _agent_prompt(agent: AgentProfile, *, current: str) -> Text:
    model = "/".join(part for part in (agent.provider, agent.model) if part) or "-"
    marker = " ◀" if agent.id.upper() == current else ""

    if marker:
        id_style = "bold"
    elif agent.color:
        id_style = f"bold {agent.color}"
    else:
        id_style = "default"

    text = Text()
    text.append(f"{agent.id:<5s}", style=id_style)
    text.append(f"{agent.name:<24s}", style="white")
    text.append(f"  {model}{marker}", style="dim")
    return text
