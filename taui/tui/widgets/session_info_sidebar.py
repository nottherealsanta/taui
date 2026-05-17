"""Right sidebar — at-a-glance info about the current session."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)] + "…"


class _SectionHeader(Static):
    """Bold section label."""


class _SectionRow(Static):
    """A single line in a section."""


class SessionInfoSidebar(VerticalScroll):
    """Right sidebar showing session info: edited files, LSP/MCP, agent, tools."""

    DEFAULT_CSS = """
    SessionInfoSidebar {
        width: 38;
        height: 100%;
        display: none;
        background: $surface;
        border-left: solid $surface-lighten-1;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #30363d $surface;
        scrollbar-color-hover: #484f58 $surface;
        scrollbar-color-active: #6e7681 $surface;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
    }
    SessionInfoSidebar.visible {
        display: block;
    }
    SessionInfoSidebar _SectionHeader {
        height: 1;
        margin: 1 0 0 0;
        text-style: bold;
        color: #e6edf3;
    }
    SessionInfoSidebar _SectionRow {
        height: auto;
        color: $text-muted;
        padding: 0 0 0 1;
    }
    SessionInfoSidebar .section-empty {
        color: #6e7681;
        padding: 0 0 0 1;
    }
    """

    BINDINGS = [("escape", "dismiss", "Dismiss")]

    class Dismiss(Message):
        pass

    _SECTION_KEYS: tuple[tuple[str, str], ...] = (
        ("session", "Session"),
        ("agent", "Agent"),
        ("files", "Files edited"),
        ("lsp", "LSP"),
        ("mcp", "MCP"),
        ("tools", "Tools"),
    )

    def compose(self) -> ComposeResult:
        for key, label in self._SECTION_KEYS:
            yield _SectionHeader(label, id=f"hdr-{key}")
            container = Vertical(id=f"sec-{key}")
            container.styles.height = "auto"
            yield container

    # ── public API ───────────────────────────────────────────────────

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.remove_class("visible")
        else:
            self.add_class("visible")

    def update_info(
        self,
        *,
        session_id: str = "",
        model: str = "",
        provider: str = "",
        agent_id: str = "",
        agent_name: str = "",
        agent_prompt_preview: str = "",
        edited_files: list[dict] | None = None,
        lsp_status: str = "",
        mcp_servers: list[tuple[str, bool]] | None = None,
        tools: list[str] | None = None,
    ) -> None:
        """Refresh all sections."""
        if not self.is_mounted:
            return
        self._render_session(session_id, model, provider)
        self._render_agent(agent_id, agent_name, agent_prompt_preview)
        self._render_files(edited_files or [])
        self._render_lsp(lsp_status)
        self._render_mcp(mcp_servers or [])
        self._render_tools(tools or [])
        self.refresh()

    # ── rendering ────────────────────────────────────────────────────

    def _replace_children(self, key: str, rows: list[Static]) -> None:
        if not self.is_mounted:
            return
        try:
            section = self.query_one(f"#sec-{key}", Vertical)
        except Exception:
            return
        section.remove_children()
        if not rows:
            section.mount(Static("—", classes="section-empty"))
            return
        for row in rows:
            section.mount(row)

    def _render_session(self, session_id: str, model: str, provider: str) -> None:
        rows: list[Static] = []
        if session_id:
            text = Text()
            text.append("id ", style="dim")
            text.append(session_id, style="bold #58a6ff")
            rows.append(_SectionRow(text))
        if model:
            text = Text()
            text.append("model ", style="dim")
            text.append(model, style="#e6edf3")
            if provider:
                text.append(f"  ({provider})", style="dim italic")
            rows.append(_SectionRow(text))
        self._replace_children("session", rows)

    def _render_agent(self, agent_id: str, agent_name: str, prompt: str) -> None:
        rows: list[Static] = []
        if agent_id:
            text = Text()
            text.append(agent_id, style="bold #d2a8ff")
            if agent_name:
                text.append(f"  {agent_name}", style="#e6edf3")
            rows.append(_SectionRow(text))
        if prompt:
            preview = _truncate(prompt.strip().splitlines()[0] if prompt.strip() else "", 80)
            rows.append(_SectionRow(Text(preview, style="dim italic")))
        self._replace_children("agent", rows)

    def _render_files(self, edited: list[dict]) -> None:
        rows: list[Static] = []
        for entry in edited:
            path = str(entry.get("path", ""))
            added = int(entry.get("added", 0))
            removed = int(entry.get("removed", 0))
            text = Text()
            text.append(_truncate(path, 28), style="#c9d1d9")
            text.append(f"  +{added}", style="#3fb950")
            text.append(f" -{removed}", style="#f97583")
            rows.append(_SectionRow(text))
        self._replace_children("files", rows)

    def _render_lsp(self, status: str) -> None:
        rows: list[Static] = []
        if status:
            rows.append(_SectionRow(Text(status, style="dim")))
        self._replace_children("lsp", rows)

    def _render_mcp(self, servers: list[tuple[str, bool]]) -> None:
        rows: list[Static] = []
        for name, online in servers:
            text = Text()
            text.append("● " if online else "○ ", style="#3fb950" if online else "#6e7681")
            text.append(name, style="#c9d1d9" if online else "dim")
            rows.append(_SectionRow(text))
        self._replace_children("mcp", rows)

    def _render_tools(self, tools: list[str]) -> None:
        rows: list[Static] = []
        if tools:
            joined = ", ".join(sorted(tools))
            rows.append(_SectionRow(Text(joined, style="dim #8b949e")))
        self._replace_children("tools", rows)

    def action_dismiss(self) -> None:
        self.remove_class("visible")
        self.post_message(self.Dismiss())
