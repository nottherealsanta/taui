"""Custom TextArea for chat input with steering/queue support."""

from __future__ import annotations

from collections.abc import Callable

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
        min-height: 1;
        max-height: 8;
        border: none;
        padding: 0 2 1 2;
        margin: 0;
        background: transparent;
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

    class AgentCycleRequested(Message):
        """Posted when the user cycles the active agent from the input."""

    class ScopeCycleRequested(Message):
        """Posted when the user toggles self-edit scope from the input."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.can_submit: bool = False
        self.agent_busy: bool = False
        self.self_edit_mode: bool = False
        self._history_messages: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""
        # Completion state (slash commands)
        self._completions: list[Completion] = []  # (name, description, accepts_args)
        self._completion_active: bool = False
        self._updating_completion_text: bool = False
        self._arg_completers: dict[str, Callable[[str], list[Completion]]] = {}

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

    def set_model_completer(
        self, completer: Callable[[str], list[Completion]] | None
    ) -> None:
        """Install completion for /model provider/model arguments."""
        self.set_arg_completer("model", completer)

    def set_arg_completer(
        self,
        command_name: str,
        completer: Callable[[str], list[Completion]] | None,
    ) -> None:
        """Install completion for a slash command's first argument."""
        name = command_name.removeprefix("/").lower()
        if completer is None:
            self._arg_completers.pop(name, None)
            return
        self._arg_completers[name] = completer

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

    def _model_arg_prefix(self) -> str | None:
        """Return the /model argument prefix when model completion applies."""
        arg_prefix = self._command_arg_prefix()
        if arg_prefix is None or arg_prefix[0] != "model":
            return None
        return arg_prefix[1]

    def _command_arg_prefix(self) -> tuple[str, str] | None:
        """Return (command, arg prefix) when command arg completion applies."""
        if not self.text.startswith("/") or " " not in self.text:
            return None
        command, arg = self.text[1:].split(" ", 1)
        command = command.lower()
        if command not in self._arg_completers:
            return None
        if " " in arg:
            return None
        return command, arg

    def _get_matching_model_args(self, prefix: str) -> list[Completion]:
        return self._get_matching_command_args("model", prefix)

    def _get_matching_command_args(
        self,
        command_name: str,
        prefix: str,
    ) -> list[Completion]:
        completer = self._arg_completers.get(command_name)
        if completer is None:
            return []
        return completer(prefix)

    def _show_completion(self) -> None:
        """Show the completion dropdown with matching commands."""
        from taui.tui.widgets.info2 import Info2

        text = self.text
        if not text.startswith("/"):
            self._dismiss_completion()
            return

        arg_prefix = self._command_arg_prefix()
        prefix = text[1:].split()[0] if text[1:].strip() else text[1:]
        dropdown_prefix = "/"
        if arg_prefix is not None:
            command_name, prefix = arg_prefix
            matches = self._get_matching_command_args(command_name, prefix)
            dropdown_prefix = ""
        elif " " in text[1:]:
            self._dismiss_completion()
            return
        else:
            matches = self._get_matching_commands(prefix)

        if not matches:
            self._dismiss_completion()
            return

        try:
            info2 = self.app.query_one(Info2)
            info2.show_completions(matches, prefix=dropdown_prefix)
            self._completion_active = True
        except Exception:
            pass

    def _dismiss_completion(self) -> None:
        """Hide the completion dropdown."""
        from taui.tui.widgets.info2 import Info2

        self._completion_active = False
        try:
            info2 = self.app.query_one(Info2)
            info2.hide()
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

    def _replace_command_arg_from_completion(
        self,
        command_name: str,
        value: str,
        *,
        trailing_space: bool,
        keep_completion: bool = False,
    ) -> None:
        """Replace a slash command's first argument with a completion."""
        self._updating_completion_text = True
        try:
            self.clear()
            suffix = " " if trailing_space else ""
            self.insert(f"/{command_name} {value}{suffix}")
        finally:
            self._updating_completion_text = False
        if not keep_completion:
            self._dismiss_completion()

    def _replace_model_arg_from_completion(
        self,
        value: str,
        *,
        trailing_space: bool,
        keep_completion: bool = False,
    ) -> None:
        """Replace the /model argument with a provider/model completion."""
        self._replace_command_arg_from_completion(
            "model",
            value,
            trailing_space=trailing_space,
            keep_completion=keep_completion,
        )

    def _fill_selected_completion(self) -> None:
        """Mirror the selected completion into the text box."""
        from taui.tui.widgets.info2 import Info2

        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
            if value:
                arg_prefix = self._command_arg_prefix()
                if arg_prefix is not None:
                    if not info2.current_accepts_args:
                        return
                    self._replace_command_arg_from_completion(
                        arg_prefix[0],
                        value,
                        trailing_space=False,
                        keep_completion=True,
                    )
                    return
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
        from taui.tui.widgets.info2 import Info2

        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
            if value:
                accepts_args = info2.current_accepts_args
                arg_prefix = self._command_arg_prefix()
                if arg_prefix is not None:
                    self._replace_command_arg_from_completion(
                        arg_prefix[0],
                        value,
                        trailing_space=True,
                    )
                    return value, accepts_args
                self._replace_text_from_completion(value, trailing_space=True)
                return value, accepts_args
        except Exception:
            self._dismiss_completion()
        return None

    def _submit_selected_completion_if_no_args(self) -> bool:
        """Submit selected no-argument command; return whether handled."""
        from taui.tui.widgets.info2 import Info2

        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
            if value and not info2.current_accepts_args:
                arg_prefix = self._command_arg_prefix()
                if arg_prefix is not None:
                    self._replace_command_arg_from_completion(
                        arg_prefix[0],
                        value,
                        trailing_space=False,
                    )
                else:
                    self._replace_text_from_completion(value, trailing_space=False)
                self._do_submit()
                return True
        except Exception:
            self._dismiss_completion()
        return False

    def _cycle_selected_command_arg_completion(self) -> bool:
        """Cycle no-argument command-arg completions without rewriting input."""
        from taui.tui.widgets.info2 import Info2

        if self._command_arg_prefix() is None:
            return False
        try:
            info2 = self.app.query_one(Info2)
            if info2.current_accepts_args:
                return False
            info2.move_down()
            return True
        except Exception:
            self._dismiss_completion()
            return False

    async def _on_key(self, event: Key) -> None:
        # Approval/model/agent/context/sessions panels own these keys when
        # active. We must stop+prevent here so TextArea._on_key (which runs
        # next in the MRO) doesn't swallow the event.
        if event.key in ("up", "down", "enter", "space", "escape"):
            from taui.tui.widgets.info2 import Info2, Info2Mode

            try:
                info2 = self.app.query_one(Info2)
                if info2.is_active and info2.mode != Info2Mode.COMPLETIONS:
                    event.stop()
                    event.prevent_default()
                    if event.key == "up":
                        info2.move_up()
                    elif event.key == "down":
                        info2.move_down()
                    elif event.key == "enter":
                        info2.accept()
                    elif event.key == "escape":
                        if info2.mode == Info2Mode.APPROVAL:
                            info2.dismiss()
                        else:
                            info2.hide()
                    return
            except Exception:
                pass

        # --- Tab ---
        if event.key == "tab":
            from taui.tui.widgets.info2 import Info2, Info2Mode

            try:
                info2 = self.app.query_one(Info2)
                if info2.is_active:
                    event.prevent_default()
                    event.stop()
                    if info2.mode == Info2Mode.COMPLETIONS:
                        if not self._submit_selected_completion_if_no_args():
                            self._accept_completion()
                    else:
                        info2.accept()
                    return
            except Exception:
                pass
            event.prevent_default()
            event.stop()
            self._dismiss_completion()
            if self.self_edit_mode:
                self.post_message(self.ScopeCycleRequested())
            else:
                self.post_message(self.AgentCycleRequested())
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
            from taui.tui.widgets.info2 import Info2

            event.prevent_default()
            event.stop()
            try:
                info2 = self.app.query_one(Info2)
                if event.key == "up":
                    info2.move_up()
                else:
                    info2.move_down()
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
        if text.startswith("/") and (
            " " not in text[1:] or self._command_arg_prefix() is not None
        ):
            self._show_completion()
        elif self._completion_active:
            self._dismiss_completion()
