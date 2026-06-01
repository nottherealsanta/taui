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
        import asyncio

        async def _run() -> None:
            try:
                await app.run_async()
            finally:
                # TUI is gone (terminal restored); clean up in the same
                # event loop that owns the MCP/LSP subprocess handles.
                await app.shutdown_resources()

        asyncio.run(_run())
    finally:
        if server is not None:
            server.stop()
    return app.resumable_session_id
