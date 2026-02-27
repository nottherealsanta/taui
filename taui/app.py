from textual.app import App, ComposeResult
from textual.widgets import Input


class Taui(App):
    """An agentic coding interface."""

    CSS = """
    Screen {
        layout: vertical;
    }

    Input {
        dock: bottom;
        padding: 1 1;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Input(placeholder="hello asdasda !")


def main() -> None:
    app = Taui()
    app.run()


if __name__ == "__main__":
    main()
