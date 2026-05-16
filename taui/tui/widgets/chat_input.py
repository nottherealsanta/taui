"""Custom TextArea for chat input with steering/queue support."""

from __future__ import annotations

import base64
import mimetypes
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from textual.events import Key, Paste
from textual.message import Message
from textual.widgets import TextArea

Completion = tuple[str, str, bool]

_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg",
})

_IMAGE_MIME_PREFIX = "image/"

_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


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

    class CancelRequested(Message):
        """Posted when user presses Escape with empty input to cancel streaming."""

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
        # Track last escape press time for double-escape detection
        self._last_escape_time: float = 0.0

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
        if user_input or self._pending_images:
            self._history_index = -1
            self._saved_input = ""
            images = self._pending_images.copy()
            self._pending_images.clear()

            # Scan text for image file paths that weren't caught by paste
            # (e.g. drag-and-drop sent as key events, or manually typed paths)
            cleaned = _extract_image_paths(user_input, images)

            self.clear()
            self._dismiss_completion()
            self.post_message(
                self.Submitted(
                    cleaned or "[Image]",
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
                self.post_message(self.ImageAttached(1))
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
            for img in images_found:
                self._pending_images.append(img)
            # Insert remaining non-image text only
            leftover = "\n".join(remaining_lines).strip()
            if leftover:
                self.insert(leftover)
            self.post_message(self.ImageAttached(len(images_found)))
            return
        # No image file paths found — let TextArea handle the paste normally.
        await super()._on_paste(event)

    class ImageAttached(Message):
        """Posted when images are attached via paste."""

        def __init__(self, count: int) -> None:
            super().__init__()
            self.count = count

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

            if event.key == "enter":
                event.prevent_default()
                event.stop()
                self._submit_selected_completion()
                return

            if event.key == "tab":
                from taui.tui.widgets.info2 import Info2, Info2Mode

                event.prevent_default()
                event.stop()
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
                self.post_message(self.ImageAttached(1))
            return

        # ── Escape ───────────────────────────────────────────────────
        if event.key == "escape":
            import time

            now = time.monotonic()
            has_content = bool(self.text.strip()) or bool(self._pending_images)
            if has_content:
                # Double-escape: clear text and attachments
                if now - self._last_escape_time < 0.4:
                    event.prevent_default()
                    event.stop()
                    self.clear()
                    self._pending_images.clear()
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
