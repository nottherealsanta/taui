"""TUI package for taui — Textual-based terminal interface."""

from taui.tui.app import TauiApp


def run_tui(config=None) -> str | None:
    """Launch the Textual TUI (blocking)."""
    from taui.config import Config

    cfg = config or Config.load()
    app = TauiApp(cfg)
    app.run()
    return app.session_id
