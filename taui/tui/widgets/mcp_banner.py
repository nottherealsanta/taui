"""Context-banner widget for connected MCP servers.

Mirrors ``ToolGroupsBanner``: a grid of ``server(N)`` cells, dim grey at rest
and brighter on hover, where N is the number of tools exposed by the
connected MCP server. Clicking the banner opens a modal listing each server
with its tool names.  Configured-but-unconnected servers show a Connect
button in the modal.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

_MCP_DEFAULT_COLOR = "#a0a0a0"
_MCP_EMPTY_COLOR = "#5a5a5a"
_DEFAULT_LABEL_STYLE = "bold #ffffff on #8a8a8a"


class McpModal(ModalScreen[None]):
    """Modal listing MCP servers — connected with tools, unconnected with a
    Connect button."""

    DEFAULT_CSS = """
    McpModal {
        align: center middle;
    }
    #mcp-modal-dialog {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #mcp-modal-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: $primary;
        text-style: bold;
    }
    #mcp-modal-dialog #mcp-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
        scrollbar-size-vertical: 1;
    }
    #mcp-modal-dialog .mcp-server {
        color: #56d4dd;
        text-style: bold;
        padding: 1 0 0 0;
    }
    #mcp-modal-dialog .mcp-server-disconnected {
        color: #5a5a5a;
        text-style: italic;
        padding: 1 0 0 0;
    }
    #mcp-modal-dialog .mcp-tool-name {
        color: $text;
        padding: 0 0 0 2;
    }
    #mcp-modal-dialog .mcp-connect-row {
        height: auto;
        padding: 0 0 0 2;
    }
    #mcp-modal-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    #mcp-modal-dialog #mcp-edit-button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        servers: dict[str, list[str]],
        *,
        mcp_manager: Any = None,
    ) -> None:
        super().__init__()
        self._servers = servers
        self._manager = mcp_manager

    def _all_server_info(self) -> list[tuple[str, bool, list[str]]]:
        """Return (name, connected, tools) for every known server."""
        result: list[tuple[str, bool, list[str]]] = []
        seen: set[str] = set()

        # Connected servers first (from payload — always accurate).
        for name in sorted(self._servers):
            result.append((name, True, self._servers[name]))
            seen.add(name)

        # Configured-but-unconnected servers from the manager.
        if self._manager is not None:
            for name in getattr(self._manager, "server_names", []) or []:
                if name not in seen:
                    result.append((name, False, []))
        return result

    def compose(self) -> ComposeResult:
        infos = self._all_server_info()
        connected_count = sum(1 for _, c, _ in infos if c)
        total_tools = sum(len(t) for _, c, t in infos if c)
        with Container(id="mcp-modal-dialog"):
            yield Static(
                f"[bold]MCP  ·  {len(infos)} server"
                f"{'s' if len(infos) != 1 else ''}"
                f"  ·  {connected_count} connected"
                f"  ·  {total_tools} tool"
                f"{'s' if total_tools != 1 else ''}[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="mcp-scroll"):
                if not infos:
                    yield Static("(no MCP servers configured)", markup=False)
                else:
                    for name, connected, tools in infos:
                        if connected:
                            yield Static(
                                f"▾ {name}  ({len(tools)})",
                                classes="mcp-server",
                                markup=False,
                            )
                            for tool in tools:
                                yield Static(
                                    f"· {tool}",
                                    classes="mcp-tool-name",
                                    markup=False,
                                )
                        else:
                            yield Static(
                                f"▸ {name}  (not connected)",
                                classes="mcp-server-disconnected",
                                markup=False,
                            )
                            with Horizontal(classes="mcp-connect-row"):
                                yield Button(
                                    "Connect",
                                    variant="default",
                                    id=f"mcp-connect-{name}",
                                )
            with Horizontal(classes="button-container"):
                yield Button(
                    "Edit MCP Server",
                    variant="default",
                    id="mcp-edit-button",
                )
                yield Button("Close", variant="primary", id="close-button")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "mcp-edit-button":
            self.dismiss(None)
            action = getattr(self.app, "action_enter_self_edit", None)
            if action is not None:
                await action(initial_category="mcp")
            return
        if bid.startswith("mcp-connect-"):
            server_name = bid[len("mcp-connect-"):]
            connect_fn = getattr(self.app, "connect_mcp_server", None)
            if connect_fn is not None:
                self.dismiss(None)
                await connect_fn(server_name)
            return
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


def _format_server_label(server: str, count: int) -> str:
    return f"{server}({count})" if count > 0 else server


def _render_columns(
    servers: dict[str, list[str]], *, color: str, columns: int = 3,
) -> str:
    if not servers:
        return ""
    labels = [
        _format_server_label(s, len(servers[s])) for s in sorted(servers)
    ]
    if not labels:
        return ""
    col_width = max((len(label) for label in labels), default=0) + 2
    rows: list[str] = []
    for i in range(0, len(labels), columns):
        chunk = labels[i:i + columns]
        cells = []
        for j, label in enumerate(chunk):
            padded = label if j == len(chunk) - 1 else label.ljust(col_width)
            cells.append(f"[{color}]{padded}[/{color}]")
        rows.append("".join(cells))
    return "\n".join(rows)


class McpBanner(Container):
    """Context banner: header label + MCP-server grid, one widget."""

    DEFAULT_CSS = """
    McpBanner {
        width: 100%;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1 0 1;
        color: #a0a0a0;
    }
    McpBanner:hover {
        background: $taui-option-active;
        color: $foreground;
    }
    McpBanner .banner-label {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0 1 0 0;
    }
    McpBanner .banner-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
        margin: 0 1 1 1;
    }
    """

    def __init__(
        self,
        servers: dict[str, list[str]],
        *,
        label_text: str = "MCP",
        label_style: str = _DEFAULT_LABEL_STYLE,
        mcp_manager: Any = None,
    ) -> None:
        super().__init__()
        self._servers = servers
        self._label_text = label_text
        self._label_style = label_style
        self._manager = mcp_manager

    def compose(self) -> ComposeResult:
        yield Static(
            self._render_label(), classes="banner-label", markup=True,
        )
        yield Static(
            self._render_body(), classes="banner-body", markup=True,
        )

    def _render_label(self) -> str:
        return f"[{self._label_style}] {self._label_text} [/]"

    def _render_body(self) -> str:
        if not self._servers:
            return f"[{_MCP_EMPTY_COLOR} italic](no MCP servers connected)[/]"
        return _render_columns(self._servers, color=_MCP_DEFAULT_COLOR)

    def set_servers(
        self,
        servers: dict[str, list[str]],
        *,
        label_style: str | None = None,
    ) -> None:
        self._servers = servers
        if label_style is not None:
            self._label_style = label_style
        try:
            self.query_one(".banner-body", Static).update(self._render_body())
            self.query_one(".banner-label", Static).update(self._render_label())
        except Exception:
            pass

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(
            McpModal(self._servers, mcp_manager=self._manager)
        )


def build_mcp_payload(mcp_manager: Any) -> dict[str, list[str]]:
    """Resolve {server -> [tool_name, ...]} for every connected MCP server."""
    if mcp_manager is None:
        return {}
    out: dict[str, list[str]] = {}
    connected = list(getattr(mcp_manager, "connected_servers", []) or [])
    for name in connected:
        client = mcp_manager.get_client(name)
        if client is None:
            continue
        tools = sorted(t.name for t in getattr(client, "tools", []) or [])
        out[name] = tools
    return out
