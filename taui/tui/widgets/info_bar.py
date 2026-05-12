"""Info bar widget — shows provider, model, tokens, and cost."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

AGENT_COLORS = {
    "DEF": "#58a6ff",
}
_AGENT_FALLBACK_COLORS = [
    "#58a6ff",
    "#f2cc60",
    "#7ee787",
    "#ff7b72",
    "#d2a8ff",
    "#79c0ff",
    "#ffa657",
    "#56d4dd",
]


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234 → '1k', 12345 → '12k', 123456 → '123k'."""
    if n < 1000:
        return str(n)
    return f"{round(n / 1000)}k"


def _agent_color(agent_id: str) -> str:
    normalized = agent_id.upper()
    if normalized in AGENT_COLORS:
        return AGENT_COLORS[normalized]
    index = sum(ord(char) for char in normalized) % len(_AGENT_FALLBACK_COLORS)
    return _AGENT_FALLBACK_COLORS[index]


class ScopeBadge(Static):
    """Active self-edit scope (project/global). Hidden when empty."""

    def set_scope(self, scope: str) -> None:
        if scope:
            self.update(
                Text.assemble(("scope: ", "italic"), (scope, "bold"))
            )
            self.display = True
        else:
            self.update("")
            self.display = False


class AgentBadge(Static):
    """Clickable active agent id."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self.agent_id = ""

    def set_agent(self, agent_id: str) -> None:
        self.agent_id = agent_id
        if agent_id:
            self.update(Text(agent_id, style=f"bold {_agent_color(agent_id)}"))
            self.display = True
        else:
            self.update("")
            self.display = False

    def on_click(self) -> None:
        if self.agent_id:
            self.post_message(InfoBar.AgentBadgeClicked(self.agent_id))


class ModelBadge(Static):
    """Clickable model id."""

    def on_click(self) -> None:
        self.post_message(InfoBar.ModelBadgeClicked())


class ProviderBadge(Static):
    """Clickable provider id."""

    def on_click(self) -> None:
        self.post_message(InfoBar.ModelBadgeClicked())


class ContextBadge(Static):
    """Clickable context token usage."""

    def on_click(self) -> None:
        self.post_message(InfoBar.ContextBadgeClicked())


class InfoBar(Horizontal):
    """Single-line bar below input showing session info."""

    class AgentBadgeClicked(Message):
        """Posted when the active agent badge is clicked."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    class ModelBadgeClicked(Message):
        """Posted when the model/provider area is clicked."""

    class ContextBadgeClicked(Message):
        """Posted when the context token area is clicked."""

    DEFAULT_CSS = """
    InfoBar {
        height: 1;
        padding: 0 2;
        margin: 0;
        color: $text-muted;
        background: transparent;
    }
    InfoBar Static {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    InfoBar #info-extension {
        margin-right: 2;
    }
    InfoBar #info-scope {
        color: #f0c808;
        margin-right: 2;
    }
    InfoBar #info-agent {
        margin-right: 2;
    }
    InfoBar #info-model {
        color: #e6edf3;
        margin-right: 2;
    }
    InfoBar #info-provider {
        color: #8b949e;
        text-style: italic;
        margin-right: 2;
    }
    InfoBar #info-tokens {
        color: #c9d1d9;
        text-style: italic;
        margin-right: 2;
    }
    InfoBar #info-cost {
        color: #c9d1d9;
        text-style: italic;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._provider = ""
        self._model = ""
        self._tokens = 0
        self._max_tokens = 0
        self._cost = 0.0
        self._extensions_mode = False
        self._agent_id = ""
        self._self_edit_scope = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="info-extension")
        yield ScopeBadge("", id="info-scope")
        yield AgentBadge(id="info-agent")
        yield ModelBadge("", id="info-model")
        yield ProviderBadge("", id="info-provider")
        yield ContextBadge("", id="info-tokens")
        yield Static("", id="info-cost")

    def update_info(
        self,
        *,
        provider: str = "",
        model: str = "",
        tokens: int = 0,
        max_tokens: int = 0,
        cost: float = 0.0,
        extensions_mode: bool = False,
        agent_id: str = "",
        self_edit_scope: str = "",
    ) -> None:
        self._provider = provider
        self._model = model
        self._tokens = tokens
        self._max_tokens = max_tokens
        self._cost = cost
        self._extensions_mode = extensions_mode
        self._agent_id = agent_id
        self._self_edit_scope = self_edit_scope
        self._sync_children()

    def _sync_children(self) -> None:
        if not self.is_mounted:
            return

        extension = self.query_one("#info-extension", Static)
        if self._extensions_mode:
            extension.update(Text(" EXT ", style="bold black on yellow"))
            extension.display = True
        else:
            extension.update("")
            extension.display = False

        self.query_one("#info-scope", ScopeBadge).set_scope(self._self_edit_scope)
        self.query_one("#info-agent", AgentBadge).set_agent(self._agent_id)
        self.query_one("#info-model", Static).update(
            self._model or Text("initializing…", style="dim italic")
        )

        provider = self.query_one("#info-provider", Static)
        provider.update(self._provider)
        provider.display = bool(self._provider)

        tokens = self.query_one("#info-tokens", Static)
        tokens.update(
            f"{_fmt_tokens(self._tokens)}/{_fmt_tokens(self._max_tokens)}"
            if self._max_tokens
            else ""
        )
        tokens.display = bool(self._max_tokens)

        cost = self.query_one("#info-cost", Static)
        cost.update(f"${self._cost:.4f}" if self._cost > 0 else "")
        cost.display = self._cost > 0

    def on_mount(self) -> None:
        self._sync_children()
