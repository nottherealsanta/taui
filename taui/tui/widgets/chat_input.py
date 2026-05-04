"""Custom TextArea for chat input with steering/queue support."""

from __future__ import annotations

from textual.events import Key
from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):
    """Chat input with Enter to submit, Shift+Enter/Ctrl+J for newline.

    Enter               → submit
    Shift+Enter / Ctrl+J → insert newline
    Alt+Enter            → insert newline (or queue if agent busy)
    Tab                  → autocomplete slash commands
    """

    DEFAULT_CSS = """
    ChatInput {
        height: auto;
        min-height: 3;
        max-height: 8;
        border: none;
        padding: 1 2;
        margin: 0 2;
        background: $surface;
        color: $text;
        scrollbar-size: 0 0;
        & .text-area--cursor-line {
            background: transparent;
        }
    }
    ChatInput:focus {
        border: none;
    }
    """

    class Submitted(Message):
        """Posted when user submits a message."""

        def __init__(self, value: str, *, queue: bool = False) -> None:
            super().__init__()
            self.value = value
            self.queue = queue

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.can_submit: bool = False
        self.agent_busy: bool = False
        self._history_messages: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""
        # Completion state
        self._completions: list[tuple[str, str]] = []  # (name, description)
        self._completion_active: bool = False

    def set_completions(self, completions: list[tuple[str, str]]) -> None:
        """Set available completions: list of (command_name, description)."""
        self._completions = completions

    def load_history(self, messages: list[str]) -> None:
        """Load message history (newest first) for Up/Down navigation."""
        self._history_messages = messages
        self._history_index = -1
        self._saved_input = ""

    def _do_submit(self, *, queue: bool = False) -> None:
        """Submit the current text if non-empty."""
        if not self.can_submit:
            return
        user_input = self.text.strip()
        if user_input:
            self._history_index = -1
            self._saved_input = ""
            self.clear()
            self._dismiss_completion()
            self.post_message(self.Submitted(user_input, queue=queue))

    def _get_matching_commands(self, prefix: str) -> list[tuple[str, str]]:
        """Return commands matching the given prefix (without /)."""
        if not prefix:
            return self._completions
        return [(n, d) for n, d in self._completions if n.startswith(prefix)]

    def _show_completion(self) -> None:
        """Show the completion dropdown with matching commands."""
        from taui.tui.widgets.completion_dropdown import CompletionDropdown
        from taui.tui.widgets.info_bar import InfoBar

        text = self.text
        if not text.startswith("/"):
            self._dismiss_completion()
            return

        prefix = text[1:].split()[0] if text[1:].strip() else text[1:]
        # Only complete if we're still typing the command name (no space yet)
        if " " in text[1:]:
            self._dismiss_completion()
            return

        matches = self._get_matching_commands(prefix)
        if not matches:
            self._dismiss_completion()
            return

        try:
            dropdown = self.app.query_one(CompletionDropdown)
            try:
                info_bar = self.app.query_one(InfoBar)
                offset_y = -(self.outer_size.height + info_bar.outer_size.height)
            except Exception:
                offset_y = -7
            dropdown.show(matches, offset_y=offset_y)
            self._completion_active = True
        except Exception:
            pass

    def _dismiss_completion(self) -> None:
        """Hide the completion dropdown."""
        from taui.tui.widgets.completion_dropdown import CompletionDropdown

        self._completion_active = False
        try:
            dropdown = self.app.query_one(CompletionDropdown)
            dropdown.hide()
        except Exception:
            pass

    def _accept_completion(self) -> None:
        """Accept the currently selected completion."""
        from taui.tui.widgets.completion_dropdown import CompletionDropdown

        try:
            dropdown = self.app.query_one(CompletionDropdown)
            value = dropdown.current_value
            if value:
                self.clear()
                self.insert(f"/{value} ")
                self._dismiss_completion()
        except Exception:
            self._dismiss_completion()

    async def _on_key(self, event: Key) -> None:
        # --- Tab ---
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            if self._completion_active:
                # Accept current selection
                self._accept_completion()
            elif self.text.startswith("/"):
                # Show completions
                self._show_completion()
                # If exactly one match, accept it immediately
                text = self.text
                prefix = text[1:].split()[0] if text[1:].strip() else text[1:]
                matches = self._get_matching_commands(prefix)
                if len(matches) == 1:
                    self.clear()
                    self.insert(f"/{matches[0][0]} ")
                    self._dismiss_completion()
            return

        # --- Escape ---
        if event.key == "escape":
            if self._completion_active:
                event.prevent_default()
                event.stop()
                self._dismiss_completion()
                return

        # --- Arrow keys while completion is active ---
        if self._completion_active and event.key in ("up", "down"):
            from taui.tui.widgets.completion_dropdown import CompletionDropdown

            event.prevent_default()
            event.stop()
            try:
                dropdown = self.app.query_one(CompletionDropdown)
                if event.key == "up":
                    dropdown.move_up()
                else:
                    dropdown.move_down()
            except Exception:
                pass
            return

        # --- Enter while completion is active ---
        if self._completion_active and event.key == "enter":
            event.prevent_default()
            event.stop()
            self._accept_completion()
            return

        # --- Shift+Enter / Ctrl+J ---
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return

        # --- Enter ---
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._do_submit()
            return

        # --- Alt+Enter ---
        if event.key == "alt+enter":
            event.prevent_default()
            event.stop()
            if self.agent_busy:
                self._do_submit(queue=True)
            else:
                self.insert("\n")
            return

        if event.key == "up":
            cursor_row = self.cursor_location[0]
            if cursor_row > 0:
                await super()._on_key(event)
                return
            event.prevent_default()
            event.stop()
            if not self._history_messages:
                return
            if self._history_index == -1:
                self._saved_input = self.text
                self._history_index = 0
            elif self._history_index < len(self._history_messages) - 1:
                self._history_index += 1
            self.clear()
            self.insert(self._history_messages[self._history_index])
            return

        if event.key == "down":
            cursor_row = self.cursor_location[0]
            last_row = self.text.count("\n")
            if cursor_row < last_row:
                await super()._on_key(event)
                return
            if self._history_index == -1:
                await super()._on_key(event)
                return
            event.prevent_default()
            event.stop()
            if self._history_index > 0:
                self._history_index -= 1
                self.clear()
                self.insert(self._history_messages[self._history_index])
            else:
                self._history_index = -1
                self.clear()
                if self._saved_input:
                    self.insert(self._saved_input)
                self._saved_input = ""
            return

        await super()._on_key(event)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Show or hide the completion dropdown as the text changes."""
        text = self.text
        if text.startswith("/") and " " not in text[1:]:
            self._show_completion()
        elif self._completion_active:
            self._dismiss_completion()
