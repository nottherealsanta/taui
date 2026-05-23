"""Custom TextArea for chat input with steering/queue support."""

from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.style import Style
from textual.binding import Binding
from textual.events import Key, Paste
from textual.message import Message
from textual.widgets import TextArea
from textual.widgets.text_area import TextAreaTheme

Completion = tuple[str, str, bool]

_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg",
})

_IMAGE_MIME_PREFIX = "image/"

_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB

# Heuristic for turning pasted text into a collapsible attachment instead of
# inlining it. Short multi-line pastes (signatures, two-line snippets) stay
# inline; anything bigger becomes a pill the user can open to view/edit.
_PASTE_ATTACH_MIN_LINES = 5
_PASTE_ATTACH_MIN_CHARS = 400


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
        padding: 1 2 1 2;
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

    BINDINGS = [
        # ── Word movement (macOS option/alt + arrow) ─────────────────
        Binding("alt+left", "cursor_word_left", "Cursor word left", show=False),
        Binding("alt+right", "cursor_word_right", "Cursor word right", show=False),
        Binding(
            "shift+alt+left,alt+shift+left",
            "cursor_word_left(True)",
            "Cursor word left select",
            show=False,
        ),
        Binding(
            "shift+alt+right,alt+shift+right",
            "cursor_word_right(True)",
            "Cursor word right select",
            show=False,
        ),
        # ── Line movement (cmd / super + arrow on macOS) ─────────────
        Binding("super+left", "cursor_line_start", "Cursor line start", show=False),
        Binding("super+right", "cursor_line_end", "Cursor line end", show=False),
        Binding(
            "shift+super+left,super+shift+left",
            "cursor_line_start(True)",
            "Cursor line start select",
            show=False,
        ),
        Binding(
            "shift+super+right,super+shift+right",
            "cursor_line_end(True)",
            "Cursor line end select",
            show=False,
        ),
        # ── Document start/end (cmd+up/down) ─────────────────────────
        Binding(
            "super+up",
            "chat_cursor_doc_start",
            "Cursor document start",
            show=False,
        ),
        Binding(
            "super+down",
            "chat_cursor_doc_end",
            "Cursor document end",
            show=False,
        ),
        Binding(
            "shift+super+up,super+shift+up",
            "chat_cursor_doc_start_select",
            "Cursor document start select",
            show=False,
        ),
        Binding(
            "shift+super+down,super+shift+down",
            "chat_cursor_doc_end_select",
            "Cursor document end select",
            show=False,
        ),
        # ── Word/line delete (alt/cmd + backspace) ───────────────────
        Binding(
            "alt+backspace",
            "delete_word_left",
            "Delete word left",
            show=False,
        ),
        Binding(
            "super+backspace",
            "delete_to_start_of_line",
            "Delete to line start",
            show=False,
        ),
        Binding(
            "alt+delete",
            "delete_word_right",
            "Delete word right",
            show=False,
        ),
        # ── Select all (cmd+a — when terminal forwards it) ───────────
        Binding("super+a", "select_all", "Select all", show=False),
    ]

    class Submitted(Message):
        """Posted when user submits a message."""

        def __init__(
            self,
            value: str,
            *,
            queue: bool = False,
            images: list[str] | None = None,
        ) -> None:
            super().__init__()
            self.value = value
            self.queue = queue
            self.images: list[str] = images or []

    class AgentCycleRequested(Message):
        """Posted when the user cycles the active agent from the input."""

    class ScopeCycleRequested(Message):
        """Posted when the user toggles self-edit scope from the input."""

    class InputCleared(Message):
        """Posted when the user double-presses Escape to clear input."""

    class AtAttachRequested(Message):
        """Posted when the user accepts an `@` completion.

        The app should attach *path* as a pill, expanding the file contents
        or folder listing into the prompt at submit time (the same shape used
        by sidebar-picked attachments).
        """

        def __init__(self, path: str, is_dir: bool) -> None:
            super().__init__()
            self.path = path
            self.is_dir = is_dir

    class CommandInvoked(Message):
        """Posted when the user picks a command mid-sentence via alt+/."""

        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    class CancelRequested(Message):
        """Posted when user presses Escape with empty input to cancel streaming."""

    _ATTACHMENT_MARKER_RE = re.compile(r"\[\d+\]")
    _ATTACHMENT_THEME_NAME = "taui-attachment-overlay"

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
        # Pending images (data: URLs) attached to the next submission
        self._pending_images: list[str] = []
        # Pending pasted-text blocks (raw text) attached to the next submission.
        # Stored separately from images so the host can show its own pill style
        # and an edit-modal for each entry.
        self._pending_pastes: list[str] = []
        # Track last escape press time for double-escape detection
        self._last_escape_time: float = 0.0
        # `@` file/folder completion. The completer takes the prefix string
        # typed after `@` and returns (relpath, is_dir) pairs. When active,
        # ``_at_range`` is (start, end) char offsets of the `@token` span in
        # ``self.text`` and ``_at_is_dir`` maps relpath → is_dir for accept.
        self._at_completer: Callable[[str], list[tuple[str, bool]]] | None = None
        self._at_range: tuple[int, int] | None = None
        self._at_is_dir: dict[str, bool] = {}
        # Configurable prefix characters
        self._file_attach_prefix: str = "@"
        self._command_prefix: str = "/"
        self._skills_prefix: str = "!"
        self._prompts_prefix: str = "#"
        self._skill_completer: Callable[
            [str], list[Completion]
        ] | None = None
        self._prompt_completer: Callable[
            [str], list[Completion]
        ] | None = None
        # Mid-sentence prefix completion (alt+/, alt+!, alt+#). The user
        # opts in explicitly via the alt-modifier so a bare `/`, `!`, or
        # `#` typed mid-sentence does *not* pop the dropdown. ``@`` keeps
        # working both ways — bare and alt+@ — via the separate at-range
        # tracking above.
        self._mid_prefix_char: str | None = None
        self._mid_prefix_range: tuple[int, int] | None = None

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

    def set_at_completer(
        self,
        completer: Callable[[str], list[tuple[str, bool]]] | None,
    ) -> None:
        """Install completion for `@<file-or-folder>` references."""
        self._at_completer = completer

    def set_skill_completer(
        self,
        completer: Callable[[str], list[Completion]] | None,
    ) -> None:
        """Install completion for skill prefix (e.g. ``!<skill>``)."""
        self._skill_completer = completer

    def set_prompt_completer(
        self,
        completer: Callable[[str], list[Completion]] | None,
    ) -> None:
        """Install completion for prompt prefix (e.g. ``#<prompt>``)."""
        self._prompt_completer = completer

    def set_prefixes(self, prefixes: dict[str, str]) -> None:
        """Configure prefix characters for file attachment and commands."""
        self._file_attach_prefix = prefixes.get("file_attach", "@")
        self._command_prefix = prefixes.get("command", "/")
        self._skills_prefix = prefixes.get("skills", "!")
        self._prompts_prefix = prefixes.get("prompts", "#")

    def _cursor_text_offset(self) -> int:
        """Return the cursor position as a character offset into ``self.text``."""
        row, col = self.cursor_location
        text = self.text
        if row == 0:
            return min(col, len(text))
        offset = 0
        for i, line in enumerate(text.split("\n")):
            if i == row:
                return offset + min(col, len(line))
            offset += len(line) + 1
        return min(offset, len(text))

    def _at_token_at_cursor(self) -> tuple[int, int, str] | None:
        """Return ``(start, end, prefix)`` for the `@token` containing the cursor."""
        return self._prefix_token_at_cursor(self._file_attach_prefix)

    def _prefix_token_at_cursor(
        self, prefix_char: str
    ) -> tuple[int, int, str] | None:
        """Return ``(start, end, query)`` for a `<prefix><word>` containing the cursor.

        The cursor must be inside (or at the right edge of) a contiguous run
        of non-whitespace characters that begins with *prefix_char*. The prefix
        itself must be at the start of the text or immediately preceded by
        whitespace. Returns ``None`` when no such token exists.
        """
        text = self.text
        offset = self._cursor_text_offset()
        i = offset
        while i > 0 and not text[i - 1].isspace():
            i -= 1
        if i >= len(text) or text[i] != prefix_char:
            return None
        if i > 0 and not text[i - 1].isspace():
            return None
        j = offset
        while j < len(text) and not text[j].isspace():
            j += 1
        return i, j, text[i + 1: j]

    def on_mount(self) -> None:
        """Register a theme that paints ``[N]`` attachment markers orange.

        Textual's TextArea only applies "highlights" when a theme is set and
        the highlight name appears in that theme's ``syntax_styles``. We
        clone the default ``css`` theme (so cursor / selection / etc. keep
        coming from CSS as before) and add the ``attachment_marker`` style.
        """
        try:
            base = TextAreaTheme.get_builtin_theme("css")
            base_styles = dict(base.syntax_styles) if base else {}
            base_styles["attachment_marker"] = Style(
                color="#ff8c00", bold=True
            )
            overlay = TextAreaTheme(
                name=self._ATTACHMENT_THEME_NAME,
                base_style=base.base_style if base else None,
                gutter_style=base.gutter_style if base else None,
                cursor_style=base.cursor_style if base else None,
                cursor_line_style=base.cursor_line_style if base else None,
                cursor_line_gutter_style=(
                    base.cursor_line_gutter_style if base else None
                ),
                bracket_matching_style=(
                    base.bracket_matching_style if base else None
                ),
                selection_style=base.selection_style if base else None,
                syntax_styles=base_styles,
            )
            self.register_theme(overlay)
            self.theme = self._ATTACHMENT_THEME_NAME
        except Exception:
            # Theming is purely cosmetic — never block startup on it.
            pass

    def _build_highlight_map(self) -> None:
        """Mark every ``[N]`` token as ``attachment_marker`` for paint pass."""
        super()._build_highlight_map()
        try:
            line_count = self.document.line_count
        except Exception:
            return
        for line_idx in range(line_count):
            try:
                line = self.document.get_line(line_idx)
            except Exception:
                continue
            for match in self._ATTACHMENT_MARKER_RE.finditer(line):
                # Highlights live in byte offsets — convert from char offsets
                # so we stay correct when the line contains non-ASCII text.
                start_byte = len(line[: match.start()].encode("utf-8"))
                end_byte = len(line[: match.end()].encode("utf-8"))
                self._highlights[line_idx].append(
                    (start_byte, end_byte, "attachment_marker")
                )

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
        if user_input or self._pending_images or self._pending_pastes:
            self._history_index = -1
            self._saved_input = ""
            images = self._pending_images.copy()
            self._pending_images.clear()

            # Scan text for image file paths that weren't caught by paste
            # (e.g. drag-and-drop sent as key events, or manually typed paths)
            cleaned = _extract_image_paths(user_input, images)

            self.clear()
            self._dismiss_completion()
            if cleaned:
                value = cleaned
            elif images:
                value = "[Image]"
            else:
                # paste-only submit — text is expanded host-side
                value = ""
            self.post_message(
                self.Submitted(
                    value,
                    queue=queue,
                    images=images or None,
                )
            )

    # ── Image helpers ─────────────────────────────────────────────────

    @property
    def pending_image_count(self) -> int:
        """Number of images attached to the next submission."""
        return len(self._pending_images)

    def attach_image(self, data_url: str) -> None:
        """Attach a data-URL encoded image to the next submission."""
        self._pending_images.append(data_url)

    def clear_images(self) -> None:
        """Remove all pending image attachments."""
        self._pending_images.clear()

    # ── Pasted-text helpers ───────────────────────────────────────────

    @property
    def pending_paste_count(self) -> int:
        """Number of pasted-text blocks attached to the next submission."""
        return len(self._pending_pastes)

    @property
    def pending_pastes(self) -> list[str]:
        """Read-only snapshot of pending pasted-text blocks."""
        return list(self._pending_pastes)

    def attach_paste(self, text: str) -> int:
        """Attach a pasted text block. Returns its index."""
        self._pending_pastes.append(text)
        return len(self._pending_pastes) - 1

    def update_paste(self, index: int, text: str) -> bool:
        """Replace the pasted text at *index*. Returns True on success."""
        if 0 <= index < len(self._pending_pastes):
            self._pending_pastes[index] = text
            return True
        return False

    def pop_paste(self, index: int) -> str | None:
        """Remove and return the pasted text at *index*, or None if missing."""
        if 0 <= index < len(self._pending_pastes):
            return self._pending_pastes.pop(index)
        return None

    def remove_paste_by_value(self, text: str) -> bool:
        """Remove the first pasted block whose text == *text*."""
        try:
            self._pending_pastes.remove(text)
            return True
        except ValueError:
            return False

    def clear_pastes(self) -> None:
        """Remove all pending paste attachments."""
        self._pending_pastes.clear()

    # ── Attachment markers ([N] tokens in the buffer) ─────────────────

    def insert_attachment_marker(self, n: int) -> None:
        """Insert ``[n]`` at the cursor."""
        self.insert(f"[{n}]")

    def remove_attachment_marker(self, n: int) -> None:
        """Remove ``[n]`` from the buffer and shift higher ``[m>n]`` down by one.

        Mirrors the renumbering ``AttachmentsBar`` does when a pill is
        removed at position ``n-1`` and all later pills slide left.
        """
        text = self.text
        target = f"[{n}]"
        idx = text.find(target)
        if idx >= 0:
            text = text[:idx] + text[idx + len(target):]

        def _shift(match: re.Match[str]) -> str:
            v = int(match.group(1))
            return f"[{v - 1}]" if v > n else match.group(0)

        new_text = re.sub(r"\[(\d+)\]", _shift, text)
        if new_text == self.text:
            return
        offset = self._cursor_text_offset()
        # Best-effort cursor preservation: shift left by the removed marker
        # if the cursor sat after it.
        if idx >= 0 and offset > idx:
            offset = max(idx, offset - len(target))
        self._updating_completion_text = True
        try:
            self.clear()
            self.insert(new_text)
            self._move_cursor_to_offset(offset)
        finally:
            self._updating_completion_text = False

    async def _on_paste(self, event: Paste) -> None:
        """Intercept paste events to detect image file paths.

        Overrides ``TextArea._on_paste`` so we can check for image paths
        *before* text is inserted into the buffer.

        Handles:
        - Plain file paths:  /Users/me/screenshot.png
        - Quoted paths:      "/Users/me/my screenshot.png"
        - Shell-escaped:     /Users/me/my\\ screenshot.png
        - file:// URIs:      file:///Users/me/screenshot.png
        - iTerm2 drag-drop:  paths with various quoting styles
        """
        import asyncio

        text = event.text.strip()

        # Empty or non-printable paste — likely a clipboard image
        if not text or _looks_like_clipboard_noise(text):
            data_url = await asyncio.to_thread(_read_clipboard_image)
            if data_url:
                self._pending_images.append(data_url)
                self.post_message(self.ImageAttached(1, data_url))
                return
            if not text:
                return
            # Fall through to normal paste if clipboard had no image either

        # Check if pasted text contains image file paths
        images_found: list[str] = []
        remaining_lines: list[str] = []

        for line in text.splitlines():
            line = line.strip()
            if not line:
                remaining_lines.append(line)
                continue

            resolved = _resolve_image_path(line)
            if resolved is not None:
                data_url = _encode_image_file(resolved)
                if data_url:
                    images_found.append(data_url)
                    continue
            remaining_lines.append(line)

        if images_found:
            # Insert remaining non-image text first so attachment markers
            # follow it at the cursor.
            leftover = "\n".join(remaining_lines).strip()
            if leftover:
                self.insert(leftover)
            for img in images_found:
                self._pending_images.append(img)
                self.post_message(self.ImageAttached(1, img))
            event.stop()
            event.prevent_default()
            return

        # Large multi-line text → attach as a pill instead of inlining.
        if _should_attach_as_paste(text):
            self._pending_pastes.append(text)
            self.post_message(
                self.PasteAttached(len(self._pending_pastes) - 1, text)
            )
            event.stop()
            event.prevent_default()
            return

        # No image file paths found — let TextArea handle the paste normally.
        # NOTE: don't call super()._on_paste(event) here. Textual's dispatcher
        # walks the MRO and invokes the parent's _on_paste automatically, so
        # calling super explicitly would insert the pasted text twice.

    class ImageAttached(Message):
        """Posted when an image is attached via paste/clipboard.

        Carries the data URL of the new image so the host can locate the
        matching pill (the chat input's pending list and the host bar stay
        in lockstep, but identifying by value is robust to reorderings).
        """

        def __init__(self, count: int, data_url: str = "") -> None:
            super().__init__()
            self.count = count
            self.data_url = data_url

    class PasteAttached(Message):
        """Posted when a multi-line paste is captured as an attachment.

        Carries the bar index assigned to the new paste and the text itself
        so the host can build a pill (and later look the entry up by value).
        """

        def __init__(self, index: int, text: str) -> None:
            super().__init__()
            self.index = index
            self.text = text

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
        if not self.text.startswith(self._command_prefix) or " " not in self.text:
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

    def _show_at_completion(self) -> bool:
        """Show file/folder completions for the `@token` under the cursor.

        Returns True when the dropdown was shown (and the slash-command path
        should be skipped), False otherwise.
        """
        from taui.tui.widgets.info2 import Info2

        if self._at_completer is None:
            return False
        token = self._at_token_at_cursor()
        if token is None:
            self._at_range = None
            return False
        start, end, prefix = token
        matches = self._at_completer(prefix)
        if not matches:
            # Keep tracking the range so the user can keep typing without
            # the panel re-opening from a stale state on the next keystroke.
            self._at_range = (start, end)
            self._at_is_dir = {}
            self._dismiss_completion()
            return True
        self._at_range = (start, end)
        self._at_is_dir = {path: is_dir for path, is_dir in matches}
        items: list[Completion] = []
        for path, is_dir in matches:
            label = f"{path}/" if is_dir else path
            desc = "folder" if is_dir else "file"
            items.append((label, desc, is_dir))
        try:
            info2 = self.app.query_one(Info2)
            info2.show_completions(items, prefix="@")
            self._completion_active = True
        except Exception:
            pass
        return True

    def _accept_at_completion(self) -> bool:
        """Accept the highlighted `@` completion: rewrite token, post attach.

        Returns True when a completion was accepted.
        """
        from taui.tui.widgets.info2 import Info2

        if self._at_range is None:
            return False
        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
        except Exception:
            value = None
        if not value:
            return False

        display = value.rstrip("/")
        is_dir = self._at_is_dir.get(display, value.endswith("/"))
        start, end = self._at_range
        text = self.text
        # Strip the `@token` (and one trailing space if present so we don't
        # leave a double space).
        cut_end = end
        if cut_end < len(text) and text[cut_end] == " ":
            cut_end += 1
        new_text = text[:start] + text[cut_end:]
        self._updating_completion_text = True
        try:
            self.clear()
            self.insert(new_text)
            # Place the cursor where the `@token` used to be.
            self._move_cursor_to_offset(start)
        finally:
            self._updating_completion_text = False
        self._at_range = None
        self._at_is_dir = {}
        self._dismiss_completion()
        self.post_message(self.AtAttachRequested(display, is_dir))
        return True

    def _move_cursor_to_offset(self, offset: int) -> None:
        """Move the cursor to a character offset within ``self.text``."""
        text = self.text
        offset = max(0, min(offset, len(text)))
        row = 0
        col = offset
        for line in text.split("\n"):
            if col <= len(line):
                break
            col -= len(line) + 1
            row += 1
        try:
            self.move_cursor((row, col))
        except Exception:
            pass

    def _show_completion(self) -> None:
        """Show the completion dropdown with matching commands."""
        from taui.tui.widgets.info2 import Info2

        text = self.text
        if not text.startswith(self._command_prefix):
            self._dismiss_completion()
            return

        arg_prefix = self._command_arg_prefix()
        prefix = text[1:].split()[0] if text[1:].strip() else text[1:]
        dropdown_prefix = self._command_prefix
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

    def _show_prefix_completion(
        self, prefix_char: str, completer: Callable[[str], list[Completion]]
    ) -> None:
        """Show completions for a single-char prefix (skills, prompts)."""
        from taui.tui.widgets.info2 import Info2

        text = self.text
        if " " in text[len(prefix_char):]:
            self._dismiss_completion()
            return
        query = text[len(prefix_char):]
        matches = completer(query)
        if not matches:
            self._dismiss_completion()
            return
        try:
            info2 = self.app.query_one(Info2)
            info2.show_completions(matches, prefix=prefix_char)
            self._completion_active = True
        except Exception:
            pass

    def _show_mid_completion(self) -> bool:
        """Show mid-sentence completion for the active alt+/ command prefix.

        Returns True when the dropdown was shown or the prefix is still being
        tracked (so the at-start completion path should be skipped). Returns
        False when the cursor has left the prefix token, clearing state.
        """
        from taui.tui.widgets.info2 import Info2

        pfx = self._mid_prefix_char
        if pfx is None:
            return False
        token = self._prefix_token_at_cursor(pfx)
        if token is None:
            self._mid_prefix_char = None
            self._mid_prefix_range = None
            self._dismiss_completion()
            return False
        start, end, query = token
        self._mid_prefix_range = (start, end)

        matches = self._get_matching_commands(query)
        if not matches:
            self._dismiss_completion()
            return True

        try:
            info2 = self.app.query_one(Info2)
            info2.show_completions(matches, prefix=pfx)
            self._completion_active = True
        except Exception:
            pass
        return True

    def _accept_mid_completion(self) -> bool:
        """Accept the selected mid-sentence command completion.

        Removes the `<prefix><token>` span from the buffer (preserving the
        rest of the user's text) and dispatches CommandInvoked so the host
        can run the slash command.
        """
        from taui.tui.widgets.info2 import Info2

        pfx = self._mid_prefix_char
        rng = self._mid_prefix_range
        if pfx is None or rng is None:
            return False
        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
        except Exception:
            value = None
        if not value:
            return False

        start, end = rng
        text = self.text
        cut_end = end
        if cut_end < len(text) and text[cut_end] == " ":
            cut_end += 1
        new_text = text[:start] + text[cut_end:]
        self._updating_completion_text = True
        try:
            self.clear()
            self.insert(new_text)
            self._move_cursor_to_offset(start)
        finally:
            self._updating_completion_text = False
        self._mid_prefix_char = None
        self._mid_prefix_range = None
        self._dismiss_completion()

        self.post_message(self.CommandInvoked(f"{pfx}{value}"))
        return True

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
        """Replace input with a prefixed completion without refreshing."""
        from taui.tui.widgets.info2 import Info2

        prefix = self._command_prefix
        try:
            info2 = self.app.query_one(Info2)
            prefix = info2._prefix or prefix
        except Exception:
            pass
        self._updating_completion_text = True
        try:
            self.clear()
            suffix = " " if trailing_space else ""
            self.insert(f"{prefix}{value}{suffix}")
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
        from taui.tui.widgets.info2 import Info2

        prefix = self._command_prefix
        try:
            info2 = self.app.query_one(Info2)
            prefix = info2._prefix or prefix
        except Exception:
            pass
        self._updating_completion_text = True
        try:
            self.clear()
            suffix = " " if trailing_space else ""
            self.insert(f"{prefix}{command_name} {value}{suffix}")
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
                # No-arg commands (e.g. /model, /agents, /sessions) act as
                # openers — submit immediately so the picker is the only
                # entry point. This avoids dual-triggering the inline arg
                # completion dropdown alongside the picker.
                if not accepts_args:
                    self._replace_text_from_completion(value, trailing_space=False)
                    self._do_submit()
                    return value, accepts_args
                self._replace_text_from_completion(value, trailing_space=True)
                return value, accepts_args
        except Exception:
            self._dismiss_completion()
        return None

    def _submit_selected_completion(self) -> bool:
        """Fill the selected completion into the buffer and submit it.

        Used by Enter when the completion dropdown is open — pressing Enter
        runs the highlighted command directly instead of merely filling it.
        """
        from taui.tui.widgets.info2 import Info2

        try:
            info2 = self.app.query_one(Info2)
            value = info2.current_value
            if value:
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
        # ── Mid-sentence command trigger (alt+/) ────────────────────────
        # Inserts the configured command prefix at the cursor and arms
        # mid-sentence completion. ``!`` / ``#`` / ``@`` are not bound here
        # because they sit behind shift on most layouts — ``@`` already
        # works mid-sentence on its own via the at-completion handler.
        if event.key == "alt+slash":
            event.prevent_default()
            event.stop()
            self._mid_prefix_char = self._command_prefix
            self.insert(self._command_prefix)
            return

        # ── Info2 panel keys (approval/model/agent/context/sessions) ──
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

        # ── Completion keys ──────────────────────────────────────────
        if self._completion_active:
            at_active = self._at_range is not None
            if event.key in ("up", "down"):
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

            mid_active = self._mid_prefix_char is not None

            if event.key == "enter":
                event.prevent_default()
                event.stop()
                if at_active:
                    self._accept_at_completion()
                elif mid_active:
                    self._accept_mid_completion()
                else:
                    self._submit_selected_completion()
                return

            if event.key == "tab":
                from taui.tui.widgets.info2 import Info2, Info2Mode

                event.prevent_default()
                event.stop()
                if at_active:
                    self._accept_at_completion()
                    return
                if mid_active:
                    self._accept_mid_completion()
                    return
                try:
                    info2 = self.app.query_one(Info2)
                    if info2.mode == Info2Mode.COMPLETIONS:
                        self._accept_completion()
                    else:
                        info2.accept()
                except Exception:
                    pass
                return

            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._at_range = None
                self._mid_prefix_char = None
                self._mid_prefix_range = None
                self._dismiss_completion()
                return

        # ── Clipboard image paste (Ctrl+V) ───────────────────────────
        if event.key == "ctrl+v":
            import asyncio

            event.prevent_default()
            event.stop()
            data_url = await asyncio.to_thread(_read_clipboard_image)
            if data_url:
                self._pending_images.append(data_url)
                self.post_message(self.ImageAttached(1, data_url))
            return

        # ── Escape ───────────────────────────────────────────────────
        if event.key == "escape":
            import time

            now = time.monotonic()
            has_content = (
                bool(self.text.strip())
                or bool(self._pending_images)
                or bool(self._pending_pastes)
            )
            if has_content:
                # Double-escape: clear text and attachments
                if now - self._last_escape_time < 0.4:
                    event.prevent_default()
                    event.stop()
                    self.clear()
                    self._pending_images.clear()
                    self._pending_pastes.clear()
                    self.post_message(self.InputCleared())
                    self._last_escape_time = 0.0
                    return
                self._last_escape_time = now
            else:
                # Empty input: cancel streaming (like Ctrl+C)
                event.prevent_default()
                event.stop()
                self._last_escape_time = 0.0
                self.post_message(self.CancelRequested())
                return

        # ── Tab (no completion active) ───────────────────────────────
        if event.key == "tab":
            from taui.tui.widgets.info2 import Info2

            event.prevent_default()
            event.stop()
            try:
                info2 = self.app.query_one(Info2)
                if info2.is_active:
                    info2.accept()
                    return
            except Exception:
                pass
            self._dismiss_completion()
            if self.self_edit_mode:
                self.post_message(self.ScopeCycleRequested())
            else:
                self.post_message(self.AgentCycleRequested())
            return

        # ── Enter ────────────────────────────────────────────────────
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._do_submit()
            return

        # ── Shift+Enter / Ctrl+J (newline) ───────────────────────────
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return

        # ── Alt+Enter (queue or newline) ─────────────────────────────
        if event.key == "alt+enter":
            event.prevent_default()
            event.stop()
            if self.agent_busy:
                self._do_submit(queue=True)
            else:
                self.insert("\n")
            return

        # ── Up arrow (history) ───────────────────────────────────────
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

        # ── Down arrow (history) ─────────────────────────────────────
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

        # ── Default: pass to TextArea ────────────────────────────────
        await super()._on_key(event)

    # ── Document start/end actions (cmd+up / cmd+down) ───────────────
    def action_chat_cursor_doc_start(self) -> None:
        self.move_cursor((0, 0), select=False)

    def action_chat_cursor_doc_start_select(self) -> None:
        self.move_cursor((0, 0), select=True)

    def action_chat_cursor_doc_end(self) -> None:
        last_row = self.document.line_count - 1
        self.move_cursor((last_row, len(self.document[last_row])), select=False)

    def action_chat_cursor_doc_end_select(self) -> None:
        last_row = self.document.line_count - 1
        self.move_cursor((last_row, len(self.document[last_row])), select=True)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Show or hide the completion dropdown as the text changes."""
        if self._updating_completion_text:
            return
        # Mid-sentence prefix completion (alt+/, alt+!, alt+#) — explicitly
        # opted in via alt-modifier so it has priority over the bare prefix
        # paths while the cursor is still inside the token.
        if self._mid_prefix_char is not None:
            if self._show_mid_completion():
                return
        # `@` completion takes priority over slash completion so users can
        # type `@<file>` while still composing a message.
        if self._show_at_completion():
            return
        self._at_range = None
        text = self.text
        if text.startswith(self._command_prefix) and (
            " " not in text[1:] or self._command_arg_prefix() is not None
        ):
            self._show_completion()
        elif (
            text.startswith(self._skills_prefix)
            and self._skill_completer is not None
        ):
            self._show_prefix_completion(
                self._skills_prefix, self._skill_completer
            )
        elif (
            text.startswith(self._prompts_prefix)
            and self._prompt_completer is not None
        ):
            self._show_prefix_completion(
                self._prompts_prefix, self._prompt_completer
            )
        elif self._completion_active:
            self._dismiss_completion()


def _encode_image_file(path: Path) -> str | None:
    """Read an image file and return a data: URL, or None on failure."""
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > _MAX_IMAGE_SIZE or size == 0:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith(_IMAGE_MIME_PREFIX):
        mime = "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _resolve_image_path(text: str) -> Path | None:
    """Try to resolve *text* to an existing image file path.

    Handles plain paths, single/double-quoted paths, shell-escaped spaces,
    ``file://`` URIs, and tilde expansion.  Returns ``None`` when *text*
    does not point to a valid image file.
    """
    candidates: list[str] = []

    # file:// URI
    if text.startswith("file://"):
        parsed = urlparse(text)
        candidates.append(unquote(parsed.path))

    # Strip surrounding quotes  ("…" or '…')
    stripped = text
    if (
        len(text) >= 2
        and (
            (text[0] == '"' and text[-1] == '"')
            or (text[0] == "'" and text[-1] == "'")
        )
    ):
        stripped = text[1:-1]
    candidates.append(stripped)

    # Un-escape shell backslash-space  (path/to/my\ file.png)
    if "\\ " in stripped:
        candidates.append(stripped.replace("\\ ", " "))

    # Original text as-is
    candidates.append(text)

    for raw in candidates:
        path = Path(raw).expanduser()
        try:
            if (
                path.suffix.lower() in _IMAGE_EXTENSIONS
                and path.is_file()
                and path.stat().st_size <= _MAX_IMAGE_SIZE
            ):
                return path
        except OSError:
            continue
    return None


def _extract_image_paths(text: str, images: list[str]) -> str:
    """Scan *text* for image file paths, encode them, append to *images*.

    Returns the text with image paths replaced by ``[Image N]`` labels.
    This catches drag-and-drop paths that arrived as key events rather
    than bracketed paste.
    """
    if not text:
        return text

    # Try the whole text as a single path first (common for drag-and-drop)
    resolved = _resolve_image_path(text)
    if resolved is not None:
        data_url = _encode_image_file(resolved)
        if data_url:
            images.append(data_url)
            return f"[Image {len(images)}]"

    # Try each line
    result_lines: list[str] = []
    found_any = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            result_lines.append(line)
            continue
        resolved = _resolve_image_path(stripped)
        if resolved is not None:
            data_url = _encode_image_file(resolved)
            if data_url:
                images.append(data_url)
                result_lines.append(f"[Image {len(images)}]")
                found_any = True
                continue
        result_lines.append(line)

    if found_any:
        return "\n".join(result_lines).strip()
    return text


def _should_attach_as_paste(text: str) -> bool:
    """Return True when *text* is big enough to warrant a paste attachment.

    Short multi-line snippets stay inline so the user can keep editing them;
    longer pastes (5+ lines or >400 chars) get tucked away in a pill so the
    chat input doesn't blow up.
    """
    if not text:
        return False
    if "\n" not in text:
        return len(text) >= _PASTE_ATTACH_MIN_CHARS
    line_count = text.count("\n") + 1
    return line_count >= _PASTE_ATTACH_MIN_LINES or len(text) >= _PASTE_ATTACH_MIN_CHARS


def _looks_like_clipboard_noise(text: str) -> bool:
    """Return True when *text* looks like terminal noise from an image paste.

    When the clipboard holds an image (not text), terminals may deliver an
    empty string, whitespace, or a short burst of control/binary characters.
    """
    if not text or text.isspace():
        return True
    # Short non-printable bursts that aren't real text
    if len(text) < 8 and not text.isprintable():
        return True
    return False


def _read_clipboard_image() -> str | None:
    """Attempt to read image data from the system clipboard.

    macOS:  uses ``osascript`` to probe clipboard type, then ``pngpaste``
            (if available) or ``osascript`` to extract PNG data.
    Linux:  uses ``xclip -selection clipboard -t image/png -o``.

    Returns a data: URL on success, or ``None``.
    """
    if sys.platform == "darwin":
        return _read_clipboard_image_macos()
    if sys.platform.startswith("linux"):
        return _read_clipboard_image_linux()
    return None


def _read_clipboard_image_macos() -> str | None:
    """Read image from macOS clipboard via pngpaste or osascript."""
    import subprocess

    # pngpaste is fast (~10ms). Use stdout mode to avoid temp files.
    pngpaste = shutil.which("pngpaste")
    if pngpaste:
        try:
            result = subprocess.run(
                [pngpaste, "-"],
                capture_output=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout:
                encoded = base64.b64encode(result.stdout).decode("ascii")
                return f"data:image/png;base64,{encoded}"
        except Exception:
            pass
        # pngpaste returns non-zero when clipboard has no image — fall through

    # Fallback: single osascript call to grab PNG data directly.
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'try\n'
                '  set pngData to (the clipboard as «class PNGf»)\n'
                '  return pngData\n'
                'on error\n'
                '  return ""\n'
                'end try',
            ],
            capture_output=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout and len(result.stdout) > 10:
            data = _parse_osascript_png(result.stdout)
            if data:
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:image/png;base64,{encoded}"
    except Exception:
        pass

    return None


def _parse_osascript_png(raw: bytes) -> bytes | None:
    """Parse PNG data from osascript «data PNGf...» output."""
    # osascript may return hex-encoded data: «data PNGf89504E47...»
    text = raw.decode("latin-1", errors="replace")
    # Look for hex data between markers
    import re
    m = re.search(r"PNGf([0-9A-Fa-f]+)", text)
    if m:
        try:
            return bytes.fromhex(m.group(1))
        except ValueError:
            pass
    # If raw bytes look like a PNG, return directly
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    return None


def _read_clipboard_image_linux() -> str | None:
    """Read image from Linux clipboard via xclip."""
    import subprocess

    xclip = shutil.which("xclip")
    if not xclip:
        return None
    try:
        result = subprocess.run(
            [xclip, "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            data = result.stdout
            if len(data) > 0 and len(data) <= _MAX_IMAGE_SIZE:
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:image/png;base64,{encoded}"
    except Exception:
        pass
    return None
