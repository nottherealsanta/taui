"""Agent picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text

from taui.self_edit import AgentProfile
from taui.tui.screens._picker_base import FuzzyPickerScreen


class AgentPickerScreen(FuzzyPickerScreen[AgentProfile]):
    """Modal for selecting an agent profile."""

    SEARCH_PLACEHOLDER = "Search agents…"
    TITLE = "Agents"

    def __init__(self, agents: list[AgentProfile], *, current: str) -> None:
        super().__init__(agents)
        self._current = current.upper()

    def render_row(self, item: AgentProfile) -> Text:
        return _agent_prompt(item, current=self._current)

    def item_id(self, item: AgentProfile) -> str:
        return item.id

    def match_text(self, item: AgentProfile) -> list[str]:
        return [item.id, item.name]


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
