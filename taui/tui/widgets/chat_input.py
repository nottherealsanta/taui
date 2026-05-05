"""Custom TextArea for chat input with steering/queue support."""

from __future__ import annotations

from textual.events import Key
from textual.message import Message
from textual.widgets import TextArea

Completion = tuple[str, str, bool]


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
        self._completions: list[Completion] = []  # (name, description, accepts_args)
        self._completion_active: bool = False
        self._updating_completion_text: bool = False

    def set_completions(self, completions: list[tuple[str, str] | Completion]) -> None:
        """Set available completions.

        Each completion is (command_name, description, accepts_args). Older
        two-item tuples default to accepting arguments for extension commands.
        """
        normalized: list[Completion] = []
        for completion in completions:
            if len(completion) == 2:
                name, description = completion
                normalized.append((name, description, True))
            else:
                name, description, accepts_args = completion
                normalized.append((name, description, accepts_args))
        self._completions = normalized

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

    def _get_matching_commands(self, prefix: str) -> list[Completion]:
        """Return commands matching the given prefix (without /)."""
        if not prefix:
            return self._completions
        return [
            (name, description, accepts_args)
            for name, description, accepts_args in self._completions
            if name.startswith(prefix)
        ]

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

    def _replace_text_from_completion(
        self,
        value: str,
        *,
        trailing_space: bool,
        keep_completion: bool = False,
    ) -> None:
        """Replace input with a slash command without refreshing the menu."""
        self._updating_completion_text = True
        try:
            self.clear()
            suffix = " " if trailing_space else ""
            self.insert(f"/{value}{suffix}")
        finally:
            self._updating_completion_text = False
        if not keep_completion:
            self._dismiss_completion()

    def _fill_selected_completion(self) -> None:
        """Mirror the selected completion into the text box."""
        from taui.tui.widgets.completion_dropdown import CompletionDropdown

        try:
            dropdown = self.app.query_one(CompletionDropdown)
            value = dropdown.current_value
            if value:
                self._replace_text_from_completion(
                    value,
                    trailing_space=False,
                    keep_completion=True,
                )
        except Exception:
            self._dismiss_completion()

    def _accept_completion(self) -> tuple[str, bool] | None:
        """Accept the currently selected completion.

        Returns (command_name, accepts_args) when a completion was accepted.
        """
        from taui.tui.widgets.completion_dropdown import CompletionDropdown

        try:
            dropdown = self.app.query_one(CompletionDropdown)
            value = dropdown.current_value
            if value:
                accepts_args = dropdown.current_accepts_args
                self._replace_text_from_completion(value, trailing_space=True)
                return value, accepts_args
        except Exception:
            self._dismiss_completion()
        return None

    def _submit_selected_completion_if_no_args(self) -> bool:
        """Submit selected no-argument command; return whether handled."""
        from taui.tui.widgets.completion_dropdown import CompletionDropdown

        try:
            dropdown = self.app.query_one(CompletionDropdown)
            value = dropdown.current_value
            if value and not dropdown.current_accepts_args:
                self._replace_text_from_completion(value, trailing_space=False)
                self._do_submit()
                return True
        except Exception:
            self._dismiss_completion()
        return False

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
                    self._replace_text_from_completion(
                        matches[0][0],
                        trailing_space=True,
                    )
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
                self._fill_selected_completion()
            except Exception:
                pass
            return

        # --- Enter while completion is active ---
        if self._completion_active and event.key == "enter":
            event.prevent_default()
            event.stop()
            if not self._submit_selected_completion_if_no_args():
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
        if self._updating_completion_text:
            return
        text = self.text
        if text.startswith("/") and " " not in text[1:]:
            self._show_completion()
        elif self._completion_active:
            self._dismiss_completion()
