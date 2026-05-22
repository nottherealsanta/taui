"""Info bar widget — shows provider, model, and tokens."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

AGENT_COLORS: dict[str, str] = {}
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


def sync_agent_colors(working_dir: Path | None = None) -> None:
    """Refresh ``AGENT_COLORS`` from the on-disk agent profiles.

    Called once at startup and again after the self-edit modal closes so
    that color changes take effect immediately.
    """
    from taui.self_edit.store import SelfEditStore

    if working_dir is None:
        return
    try:
        profiles = SelfEditStore(working_dir).load_agents()
    except Exception:
        return
    AGENT_COLORS.clear()
    for agent_id, profile in profiles.items():
        color = str(getattr(profile, "color", "") or "").strip()
        if color:
            AGENT_COLORS[agent_id.upper()] = color


def _agent_color(agent_id: str) -> str:
    normalized = agent_id.upper()
    if normalized in AGENT_COLORS:
        return AGENT_COLORS[normalized]
    index = sum(ord(char) for char in normalized) % len(_AGENT_FALLBACK_COLORS)
    return _AGENT_FALLBACK_COLORS[index]


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


class VariantBadge(Static):
    """Clickable model variant (reasoning effort / thinking level)."""

    def on_click(self) -> None:
        self.post_message(InfoBar.VariantBadgeClicked())


class ContextBadge(Static):
    """Clickable context token usage."""

    def on_click(self) -> None:
        self.post_message(InfoBar.ContextBadgeClicked())


class InfoBar(Static):
    """Two-line bar below input showing session info."""

    class AgentBadgeClicked(Message):
        """Posted when the active agent badge is clicked."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    class ModelBadgeClicked(Message):
        """Posted when the model/provider area is clicked."""

    class VariantBadgeClicked(Message):
        """Posted when the model-variant badge is clicked."""

    class ContextBadgeClicked(Message):
        """Posted when the context token area is clicked."""

    DEFAULT_CSS = """
    InfoBar {
        height: 2;
        padding: 0 2 0 2;
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
    InfoBar #info-row-1 {
        height: 1;
    }
    InfoBar #info-row-2 {
        height: 1;
        align: right middle;
    }
    InfoBar #info-extension {
        margin-right: 2;
    }
    InfoBar #info-agent {
        margin-right: 2;
    }
    InfoBar #info-model {
        color: $foreground;
        margin-right: 2;
    }
    InfoBar #info-provider {
        color: $text-muted;
        text-style: italic;
        margin-right: 2;
    }
    InfoBar #info-variant {
        color: $foreground-darken-2;
        margin-right: 2;
    }
    InfoBar #info-tokens {
        color: #707070;
    }
    InfoBar #info-worktree {
        color: $foreground;
        margin-right: 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._provider = ""
        self._variant = ""
        self._model = ""
        self._tokens = 0
        self._max_tokens = 0
        self._extensions_mode = False
        self._agent_id = ""
        self._plan_mode = False
        self._worktree_branch = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="info-row-1"):
            yield Static("", id="info-extension")
            yield AgentBadge(id="info-agent")
            yield ModelBadge("", id="info-model")
            yield ProviderBadge("", id="info-provider")
            yield VariantBadge("", id="info-variant")
            yield Static("", id="info-worktree")
        with Horizontal(id="info-row-2"):
            yield ContextBadge("", id="info-tokens")

    def update_info(
        self,
        *,
        provider: str = "",
        model: str = "",
        variant: str = "",
        tokens: int = 0,
        max_tokens: int = 0,
        extensions_mode: bool = False,
        agent_id: str = "",
        plan_mode: bool = False,
        worktree_branch: str = "",
    ) -> None:
        self._provider = provider
        self._variant = variant
        self._model = model
        self._tokens = tokens
        self._max_tokens = max_tokens
        self._extensions_mode = extensions_mode
        self._agent_id = agent_id
        self._plan_mode = plan_mode
        self._worktree_branch = worktree_branch
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

        # Plan mode indicator (after extension indicator)
        if self._plan_mode and not self._extensions_mode:
            extension.update(
                Text(" PLAN ", style="bold black on #d2a8ff")
            )
            extension.display = True

        self.query_one("#info-agent", AgentBadge).set_agent(self._agent_id)
        self.query_one("#info-model", Static).update(
            self._model or Text("initializing…", style="dim italic")
        )

        provider = self.query_one("#info-provider", Static)
        provider.update(self._provider)
        provider.display = bool(self._provider)

        variant = self.query_one("#info-variant", Static)
        variant.update(self._variant)
        variant.display = bool(self._variant)

        tokens = self.query_one("#info-tokens", Static)
        if self._max_tokens:
            pct = min(round(self._tokens / self._max_tokens * 100), 100)
            tokens.update(f"{_fmt_tokens(self._tokens)} ({pct}%)")
            tokens.display = True
        else:
            tokens.update("")
            tokens.display = False

        worktree = self.query_one("#info-worktree", Static)
        if self._worktree_branch:
            worktree.update(
                Text(f" ⌥ {self._worktree_branch} ", style="bold black on #79c0ff")
            )
            worktree.display = True
        else:
            worktree.update("")
            worktree.display = False


    def on_mount(self) -> None:
        self._sync_children()
