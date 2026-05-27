"""TUI package for taui — Textual-based terminal interface."""

from taui.tui.app import TauiApp


def run_tui(
    config=None,
    *,
    debug: bool = False,
    debug_socket: str | None = None,
) -> str | None:
    """Launch the Textual TUI (blocking).

    When ``debug=True`` an embedded MCP server is started on a Unix
    socket alongside the live app, so external clients can drive it.
    """
    from taui.config import Config

    cfg = config or Config.load()
    app = TauiApp(cfg)

    server = None
    if debug:
        from taui.debug.server import DebugServer

        server = DebugServer(app, socket_path=debug_socket)
        server.start()
    try:
        app.run()
    finally:
        if server is not None:
            server.stop()
    return app.resumable_session_id
