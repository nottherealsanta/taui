"""Agent picker modal screen."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from taui.self_edit import AgentProfile


class AgentPickerScreen(ModalScreen[str | None]):
    """Modal for selecting an agent profile."""

    DEFAULT_CSS = """
    AgentPickerScreen {
        align: center middle;
    }
    #agent-picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #agent-picker-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #agent-picker-dialog OptionList {
        height: auto;
        max-height: 18;
    }
    #agent-picker-dialog .hint {
        padding: 1 0 0 0;
        color: $text-muted;
    }
    """

    def __init__(self, agents: list[AgentProfile], *, current: str) -> None:
        super().__init__()
        self._agents = agents[:50]
        self._current = current.upper()

    def compose(self) -> ComposeResult:
        with Container(id="agent-picker-dialog"):
            yield Label("[bold]Select Agent[/bold]", classes="dialog-title")
            yield OptionList(
                *[
                    Option(_agent_prompt(agent, current=self._current), id=agent.id)
                    for agent in self._agents
                ],
                id="agent-options",
            )
            yield Label("Enter to select, Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#agent-options", OptionList).focus()

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


def _agent_prompt(agent: AgentProfile, *, current: str) -> Text:
    model = "/".join(part for part in (agent.provider, agent.model) if part) or "-"
    marker = " ◀" if agent.id.upper() == current else ""

    text = Text()
    text.append(f"{agent.id:<5s}", style="bold cyan" if marker else "white")
    text.append(f"{agent.name:<24s}", style="white")
    text.append(f"  {model}{marker}", style="dim")
    return text
