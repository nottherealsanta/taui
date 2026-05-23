"""Main Textual application for taui."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.command import CommandInput, CommandPalette
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Key
from textual.screen import Screen
from textual.system_commands import SystemCommandsProvider
from textual.widgets import Markdown, Static, Tree

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, estimate_total_tokens
from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.config import Config
from taui.self_edit.store import AgentProfile, SelfEditStore
from taui.session import Session
from taui.tui.approval_controller import ApprovalController
from taui.tui.messages import (
    AgentConfigChanged,
    CompactionOccurred,
    StreamReasoningDelta,
    StreamTextDelta,
    ToolEnded,
    ToolStarted,
)
from taui.tui.screens.context_breakdown import ContextBreakdownScreen
from taui.tui.screens.git_diff import GitDiffScreen
from taui.tui.screens.pasted_content import PastedContentScreen, PasteResult
from taui.tui.screens.theme_picker import ThemePickerScreen
from taui.tui.screens.variant_picker import VariantPickerScreen
from taui.tui.session_state import SessionManager, SessionState
from taui.tui.theme import ALL_THEMES, TAUI_DARK
from taui.tui.tool_controller import ToolController
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.info_bar import InfoBar, _agent_color, sync_agent_colors
from taui.tui.widgets.reply_footer import ReplyFooter
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.spinner import ActivityProgress
from taui.tui.widgets.tool_status import ToolStatusWidget
from taui.tui.widgets.turn_container import TurnContainer

logger = logging.getLogger(__name__)


class TauiApp(App[None]):
    """Textual TUI for taui."""

    TITLE = "taui"

    COMMANDS = {
        SystemCommandsProvider,
    }

    CSS_PATH = "app.tcss"

    BINDINGS = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+n", "new_chat", "New session"),
        ("ctrl+c", "cancel_request", "Cancel"),
        ("ctrl+d", "ctrl_d", ""),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+r", "toggle_info_sidebar", "Info"),
        ("ctrl+x", "show_context", "Context"),
        ("alt+left", "focus_pane_left", "Focus left pane"),
        ("alt+right", "focus_pane_right", "Focus right pane"),
        ("ctrl+pagedown", "next_tab", "Next tab"),
        ("ctrl+pageup", "prev_tab", "Prev tab"),
        ("escape", "escape", ""),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        # Register taui themes before anything else touches styling.
        for theme in ALL_THEMES:
            self.register_theme(theme)
        self.theme = TAUI_DARK.name
        self._config = config or Config.load()
        self._sessions = SessionManager()
        self._session_initializing = False

        # Double-press quit tracking
        self._last_ctrl_c_time: float = 0.0
        self._last_ctrl_d_time: float = 0.0

        # History persistence
        self._history_file = Path.home() / ".cache" / "taui" / "prompt_history"
        self._history: list[str] = []

        # Files attached via the left sidebar's Files tab. Their contents are
        # inlined into the prompt on submit, then this list is cleared.
        self._pending_files: list[Path] = []
        # Folders attached the same way — expanded as a tree listing.
        self._pending_folders: list[Path] = []

        # Window focus state — terminals send AppFocus/AppBlur via DEC
        # mode 1004 (Textual enables this by default). Assume focused at
        # startup; AppBlur flips it.
        self._window_focused: bool = True

    # ── Backward-compatible property accessors ────────────────────────
    # These delegate to the active SessionState so the rest of the code
    # (which was written for single-session) keeps working unchanged.

    @property
    def _session(self) -> Session | None:
        state = self._sessions.active
        return state.session if state else None

    @_session.setter
    def _session(self, value: Session | None) -> None:
        # Used during init, tests, and close
        if value is None:
            # Clearing — used by _close_cleanly in tests
            if self._sessions.active_id:
                self._sessions.remove(self._sessions.active_id)
            return
        state = self._sessions.active
        if state is not None:
            state.session = value
            # Update session_id if changed
            sid = getattr(value, "session_id", None) or state.session_id
            if sid != state.session_id:
                old_id = state.session_id
                state.session_id = sid
                self._sessions._states.pop(old_id, None)
                if old_id in self._sessions._order:
                    idx = self._sessions._order.index(old_id)
                    self._sessions._order[idx] = sid
                self._sessions._states[sid] = state
                self._sessions.active_id = sid
        else:
            # No active state yet — create one (e.g. test setup)
            sid = getattr(value, "session_id", None) or "default"
            new_state = SessionState(
                session=value,
                session_id=sid,
                tool_ctrl=ToolController(self),
                approval_ctrl=ApprovalController(self),
            )
            self._sessions.add(new_state)
            self._sessions.active_id = sid

    @property
    def _is_processing(self) -> bool:
        state = self._sessions.active
        return state.is_processing if state else False

    @_is_processing.setter
    def _is_processing(self, value: bool) -> None:
        state = self._sessions.active
        if state is not None:
            state.is_processing = value

    @property
    def _tool_ctrl(self) -> ToolController:
        state = self._sessions.active
        if state is not None and state.tool_ctrl is not None:
            return state.tool_ctrl
        # Fallback: create a default state so mutations persist (test compat)
        if not self._sessions.order:
            default_state = SessionState(
                session=None,  # type: ignore[arg-type]
                session_id="__fallback__",
                tool_ctrl=ToolController(self),
                approval_ctrl=ApprovalController(self),
            )
            self._sessions.add(default_state)
            self._sessions.active_id = "__fallback__"
            return default_state.tool_ctrl
        return ToolController(self)

    @property
    def _approval_ctrl(self) -> ApprovalController:
        state = self._sessions.active
        if state is not None and state.approval_ctrl is not None:
            return state.approval_ctrl
        return ApprovalController(self)

    @property
    def _current_response(self) -> AgentResponse | None:
        state = self._sessions.active
        return state.current_response if state else None

    @_current_response.setter
    def _current_response(self, value: AgentResponse | None) -> None:
        state = self._sessions.active
        if state is not None:
            state.current_response = value

    @property
    def _current_reasoning(self) -> Static | None:
        state = self._sessions.active
        return state.current_reasoning if state else None

    @_current_reasoning.setter
    def _current_reasoning(self, value: Static | None) -> None:
        state = self._sessions.active
        if state is not None:
            state.current_reasoning = value

    @property
    def _reasoning_buf(self) -> str:
        state = self._sessions.active
        return state.reasoning_buf if state else ""

    @_reasoning_buf.setter
    def _reasoning_buf(self, value: str) -> None:
        state = self._sessions.active
        if state is not None:
            state.reasoning_buf = value

    @property
    def _streamed_text(self) -> bool:
        state = self._sessions.active
        return state.streamed_text if state else False

    @_streamed_text.setter
    def _streamed_text(self, value: bool) -> None:
        state = self._sessions.active
        if state is not None:
            state.streamed_text = value

    @property
    def _reply_footer(self) -> ReplyFooter | None:
        state = self._sessions.active
        return state.reply_footer if state else None

    @_reply_footer.setter
    def _reply_footer(self, value: ReplyFooter | None) -> None:
        state = self._sessions.active
        if state is not None:
            state.reply_footer = value

    @property
    def _queued(self) -> list[tuple[str, list[str] | None]]:
        state = self._sessions.active
        return state.queued if state else []

    @_queued.setter
    def _queued(self, value: list) -> None:
        state = self._sessions.active
        if state is not None:
            state.queued = value

    @property
    def _pending_indicators(self) -> list[tuple[str, str]]:
        state = self._sessions.active
        return state.pending_indicators if state else []

    @_pending_indicators.setter
    def _pending_indicators(self, value: list) -> None:
        state = self._sessions.active
        if state is not None:
            state.pending_indicators = value

    @property
    def _edited_files(self) -> dict[str, dict[str, int]]:
        state = self._sessions.active
        return state.edited_files if state else {}

    @_edited_files.setter
    def _edited_files(self, value: dict) -> None:
        state = self._sessions.active
        if state is not None:
            state.edited_files = value

    @property
    def _context_banner_shown(self) -> bool:
        state = self._sessions.active
        return state.context_banner_shown if state else False

    @_context_banner_shown.setter
    def _context_banner_shown(self, value: bool) -> None:
        state = self._sessions.active
        if state is not None:
            state.context_banner_shown = value

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Return command-palette entries — only /slash commands."""
        yield from self._taui_palette_commands()

    def _taui_palette_commands(self) -> Iterable[SystemCommand]:
        """Build command-palette entries — every registered /slash command."""
        commands = getattr(self, "_commands", None)
        if commands is None:
            return
        for name in commands.names:
            command = commands.get(name)
            if command is None:
                continue
            yield SystemCommand(
                f"/{name}",
                command.description,
                lambda name=name: self._run_palette_command(f"/{name}"),
            )

    def _run_palette_command(self, command: str) -> None:
        """Run a slash command selected from the command palette."""
        worker_name = "palette_" + command.lstrip("/").split(maxsplit=1)[0]
        self.run_worker(
            self._handle_command(command),
            name=worker_name,
            group="palette",
            exclusive=False,
        )

    @property
    def session_id(self) -> str | None:
        """Current active session id, if a session exists."""
        return self._session.session_id if self._session else None

    @property
    def _tool_counter(self) -> int:
        return self._tool_ctrl._tool_counter

    @_tool_counter.setter
    def _tool_counter(self, value: int) -> None:
        self._tool_ctrl._tool_counter = value

    @property
    def _pending_tool_keys(self) -> dict[str, list[str]]:
        return self._tool_ctrl._pending_tool_keys

    @property
    def _active_tool_widgets(self) -> dict[str, object]:
        return self._tool_ctrl._active_tool_widgets

    LAYERS = ("default", "overlay")

    def compose(self) -> ComposeResult:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        with Horizontal(id="main-layout"):
            yield Sidebar(self._config.working_dir)
            with Vertical(id="chat-area"):
                with Vertical(id="chat-log-container"):
                    pass
                yield Info2(id="info2")
                with Vertical(id="chat-container"):
                    yield AttachmentsBar(id="attachments-bar")
                    chat_input = ChatInput(
                        id="chat-input",
                        language=None,
                        show_line_numbers=False,
                    )
                    chat_input.display = False
                    yield chat_input
                    yield InfoBar()
                yield ActivityProgress(id="activity-progress")
            yield SessionInfoSidebar()

    async def on_mount(self) -> None:
        sync_agent_colors(self._config.working_dir)
        self._commands = self._build_commands()
        self._configure_chat_input()
        self._session_initializing = True
        self.query_one(InfoBar).update_info(
            provider=self._config.provider,
            model=self._config.model,
            variant=self._config.model_variant,
            agent_id="" if self._config.session_id else "DEF",
        )
        self._set_chat_panel_visible(False)
        self.query_one(ActivityProgress).start_breathing()

        self.run_worker(
            self._initialize_session(),
            name="session_init",
            group="startup",
            exclusive=True,
            exit_on_error=False,
        )

        # Refresh the models.dev catalog in the background if the local cache
        # is older than the TTL. Runs out-of-band so a slow fetch never
        # blocks startup. list_models / fetch_models handle their own cache
        # gate; we just kick the work off.
        self.run_worker(
            self._refresh_models_catalog_if_stale(),
            name="models_refresh",
            group="startup",
            exclusive=False,
            exit_on_error=False,
        )

    def _set_chat_panel_visible(self, visible: bool) -> None:
        """Show/hide the chat panel contents while keeping the bottom bar."""
        for selector in ("#chat-log-container", "#info2", "#chat-container"):
            try:
                self.query_one(selector).display = visible
            except Exception:
                pass

    async def _refresh_models_catalog_if_stale(self) -> None:
        """Trigger a models.dev fetch off the main thread when cache is old.

        fetch_models() itself decides whether to hit the network — calling
        it without ``force=True`` is a no-op when the cache is fresh.
        """
        try:
            from taui.llm_provider import models as models_mod

            await asyncio.to_thread(models_mod.fetch_models)
        except Exception:
            # Network or disk problems shouldn't crash startup; the user can
            # always invoke /update-providers-models manually.
            logger.debug("Background models refresh failed", exc_info=True)

    async def _initialize_session(self) -> None:
        try:
            session = await Session.create(self._config)
        except Exception as exc:
            logger.exception("Failed to create session")
            self._session_initializing = False
            self.query_one(ActivityProgress).stop()
            self._set_chat_panel_visible(True)
            await self._show_startup_error(exc)
            return

        await self._add_session(session)

        if not self._config.session_id:
            self._apply_default_agent_profile()
        self._wire_callbacks()
        self._update_status()
        self._session_initializing = False

        self.query_one(ActivityProgress).stop()
        self._set_chat_panel_visible(True)
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.display = True
        chat_input.focus()

        if self._config.session_id:
            await self._resume_session(self._config.session_id)

    async def _add_session(self, session: Session) -> SessionState:
        """Create a SessionState for *session*, mount its chat log, and activate it."""
        sid = session.session_id or "init"
        state = SessionState(
            session=session,
            session_id=sid,
            tool_ctrl=ToolController(self),
            approval_ctrl=ApprovalController(self),
        )

        # Create a per-session chat log widget
        chat_log = VerticalScroll(id=f"chat-log-{sid}")
        state.chat_log = chat_log

        # Hide all existing chat logs
        container = self.query_one("#chat-log-container", Vertical)
        for child in container.children:
            if isinstance(child, VerticalScroll):
                child.add_class("hidden-chat-log")

        await container.mount(chat_log)
        chat_log.anchor()
        await self._mount_splash(chat_log)

        self._sessions.add(state)
        self._sessions.active_id = sid
        self._refresh_tab_bar()
        return state

    def _refresh_tab_bar(self) -> None:
        """No-op — session tab bar has been removed."""
        return

    def _get_active_chat_log(self) -> VerticalScroll:
        """Return the active session's chat log widget."""
        state = self._sessions.active
        if state is not None and state.chat_log is not None:
            return state.chat_log
        # Fallback: find any chat log in the container
        container = self.query_one("#chat-log-container", Vertical)
        for child in container.children:
            if isinstance(child, VerticalScroll):
                return child
        # Last resort: create one
        raise NoMatches("No chat log found")

    def _configure_chat_input(self) -> None:
        """Load input history and command completions."""
        # Load history
        self._load_history()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.load_history(self._history)
        chat_input.set_model_completer(self._complete_model_arg)
        chat_input.set_arg_completer("agents", self._complete_agents_arg)
        chat_input.set_at_completer(self._complete_at_attachment)
        chat_input.set_skill_completer(self._complete_skill)
        chat_input.set_prompt_completer(self._complete_prompt)
        chat_input.set_prefixes(self._config.prefixes)
        self._refresh_command_completions()
        chat_input.can_submit = True

    def _refresh_command_completions(self) -> None:
        """Rebuild the slash-command completion list, gating /exit on self-edit."""
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
        except Exception:
            return
        completions: list[tuple[str, str, bool]] = []
        if self._session is not None and self._session.self_edit_mode:
            completions.append(("exit", "Return to main session", False))
        for name in self._commands.names:
            command = self._commands.get(name)
            if command is not None:
                completions.append(
                    (
                        name,
                        command.description,
                        getattr(command, "accepts_args", True),
                    )
                )
        chat_input.set_completions(completions)

    def _empty_registry(self):
        from taui.tools.registry import ToolRegistry

        return ToolRegistry()

    async def _show_startup_error(self, exc: Exception) -> None:
        """Render a startup failure without letting Textual print a traceback."""
        # No session exists yet — mount a temporary chat log in the container
        container = self.query_one("#chat-log-container", Vertical)
        chat_log = VerticalScroll(id="chat-log-error")
        await container.mount(chat_log)
        provider = self._config.provider
        message = str(exc) or exc.__class__.__name__
        await chat_log.mount(
            Static(
                "[red]Could not start session.[/red]\n"
                f"[dim]Provider:[/dim] {escape(provider)}\n"
                f"[dim]Reason:[/dim] {escape(message)}\n\n"
                "[dim]Run `taui --login` after fixing auth/network access, "
                "or start with another provider via `taui -p <provider>`.[/dim]",
                markup=True,
            )
        )
        info_bar = self.query_one(InfoBar)
        info_bar.update_info(provider=provider, model=self._config.model)

    # ── History persistence ───────────────────────────────────────────

    def _load_history(self) -> None:
        """Load prompt history from disk (newest first)."""
        try:
            if self._history_file.exists():
                lines = self._history_file.read_text().strip().splitlines()
                # Each line stores `\n` as the literal sequence `\\n`; decode
                # back to a real newline so recalled messages keep their shape.
                decoded = [
                    line.replace("\\\\", "\x00")
                        .replace("\\n", "\n")
                        .replace("\x00", "\\")
                    for line in lines
                ]
                # File stores oldest first; we want newest first
                self._history = list(reversed(decoded[-500:]))
        except Exception:
            self._history = []

    def _save_to_history(self, text: str) -> None:
        """Append a message to history (on disk and in memory)."""
        self._history.insert(0, text)
        if len(self._history) > 500:
            self._history = self._history[:500]
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with self._history_file.open("a") as f:
                # Escape backslashes first so `\\n` literals round-trip
                # cleanly through the newline-encoding step.
                encoded = text.replace("\\", "\\\\").replace("\n", "\\n")
                f.write(encoded + "\n")
        except Exception:
            pass
        # Update ChatInput's history
        self.query_one("#chat-input", ChatInput).load_history(self._history)

    # ── @file expansion ───────────────────────────────────────────────

    def _render_bar_attachments(
        self, text: str, images: list[str] | None
    ) -> tuple[str, str, list[str] | None]:
        """Replace ``[N]`` markers in *text* using attachment-bar items.

        Returns ``(chat_log_text, llm_text, images)``:

        - ``[N]`` for paste pills → ``[Pasted <tokens>t]`` in the chat log
          and a fenced ``text`` block in the LLM-bound message.
        - ``[N]`` for image pills (clipboard / drag-drop) → ``[Image M]``
          where M is the image's 1-based position in the final list.
        - ``[N]`` for file pills → ``[Image M]`` (image suffix) or
          ``@<relpath>`` otherwise.
        - ``[N]`` for folder pills → ``@<relpath>/``.

        Image bar pills are already present in *images* (kept in pill
        order by ``ChatInput``); only sidebar-attached image files are
        appended here. Tokens are estimated as ``max(1, nchars // 4)``.
        """
        from taui.tui.widgets.chat_input import (
            _IMAGE_EXTENSIONS,
            _encode_image_file,
        )

        bar = self.query_one(AttachmentsBar)
        items = bar.items
        out_images: list[str] = list(images or [])
        chat_repl: dict[int, str] = {}
        llm_repl: dict[int, str] = {}
        image_seq = 0  # 1-based index over image-kind pills

        for i, item in enumerate(items):
            n = i + 1
            if item.kind == "image":
                image_seq += 1
                label = f"[Image {image_seq}]"
                chat_repl[n] = label
                llm_repl[n] = label
            elif item.kind == "paste":
                tokens = max(1, len(item.data) // 4)
                chat_repl[n] = f"[Pasted {tokens}t]"
                llm_repl[n] = f"\n```text\n{item.data}\n```\n"
            elif item.kind == "file":
                path = Path(item.data)
                is_image = False
                try:
                    is_image = path.suffix.lower() in _IMAGE_EXTENSIONS
                except OSError:
                    is_image = False
                if is_image:
                    data_url = _encode_image_file(path)
                    if data_url:
                        out_images.append(data_url)
                        label = f"[Image {len(out_images)}]"
                        chat_repl[n] = label
                        llm_repl[n] = label
                        continue
                try:
                    display = path.relative_to(self._config.working_dir)
                except ValueError:
                    display = path
                ref = f"@{display}"
                chat_repl[n] = ref
                llm_repl[n] = ref
            elif item.kind == "folder":
                path = Path(item.data)
                try:
                    display = path.relative_to(self._config.working_dir)
                except ValueError:
                    display = path
                ref = f"@{display}/"
                chat_repl[n] = ref
                llm_repl[n] = ref

        def _make_sub(table: dict[int, str]):
            def _sub(match: re.Match[str]) -> str:
                v = int(match.group(1))
                return table.get(v, match.group(0))
            return _sub

        chat_text = re.sub(r"\[(\d+)\]", _make_sub(chat_repl), text)
        llm_text = re.sub(r"\[(\d+)\]", _make_sub(llm_repl), text)
        return chat_text, llm_text, (out_images or None)

    def _expand_file_refs(self, text: str) -> tuple[str, list[str] | None]:
        """Resolve `@path` references.

        Images become inline data-URL attachments (the model can't fetch
        them via tools). Text files and folders are left as `@path`
        literals so the path is in context but the body is not — the
        model can call `read`/`grep` if it needs the contents.
        """
        from taui.tui.widgets.chat_input import _IMAGE_EXTENSIONS, _encode_image_file

        # Preserve whitespace so multi-line @-refs survive intact.
        tokens = re.split(r"(\s+)", text)
        result: list[str] = []
        images: list[str] = []
        for token in tokens:
            fa_prefix = self._config.prefixes.get("file_attach", "@")
            if token.startswith(fa_prefix) and len(token) > len(fa_prefix):
                fpath = Path(token[len(fa_prefix):])
                if not fpath.is_absolute():
                    fpath = self._config.working_dir / fpath
                if (
                    fpath.is_file()
                    and fpath.suffix.lower() in _IMAGE_EXTENSIONS
                ):
                    data_url = _encode_image_file(fpath)
                    if data_url:
                        images.append(data_url)
                        result.append(f"[Image {len(images)}]")
                        continue
            result.append(token)
        return "".join(result), images or None

    # ── Command registry ──────────────────────────────────────────────

    def _build_commands(self) -> CommandRegistry:
        registry = CommandRegistry()
        register_builtin_commands(
            registry,
            get_session=lambda: self._session,
            get_tracker=lambda: (
                self._session.cost_tracker if self._session else None
            ),
            get_extensions=lambda: (
                self._session._ext_registry if self._session else None
            ),
            get_store=lambda: SelfEditStore(self._config.working_dir),
            get_apply_profile=self._apply_self_edit_profile,
        )
        return registry

    def _complete_model_arg(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Complete /model arguments as provider/model_id."""
        from taui.llm_provider.models import list_models

        if self._session is None:
            return []
        provider = self._session.config.provider
        completions: list[tuple[str, str, bool]] = []
        for model in list_models(provider):
            value = f"{provider}/{model['id']}"
            if prefix and not _model_completion_matches(prefix, provider, model["id"]):
                continue
            ctx = f"{model['context'] // 1000}k" if model["context"] else "?"
            tag = " reasoning" if model["reasoning"] else ""
            completions.append((value, f"{ctx} ctx{tag}", True))
            if len(completions) >= 30:
                break
        return completions[:30]

    def _complete_agents_arg(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Complete /agents arguments as profile IDs."""
        store = SelfEditStore(self._config.working_dir)
        agents = store.load_agents()
        matches: list[tuple[str, str, bool]] = []
        for agent in sorted(agents.values(), key=lambda item: item.id):
            if agent.subagent_only:
                continue
            if prefix and not _fuzzy_match(prefix.lower(), agent.id.lower()):
                continue
            matches.append((agent.id, agent.name, False))
        return matches

    def _complete_at_attachment(self, prefix: str) -> list[tuple[str, bool]]:
        """Complete `@<file>` references with files/folders from the project."""
        completer = self._ensure_at_completer()
        return completer.complete(prefix)

    def _complete_skill(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Complete skill names for the skill prefix."""
        if self._session is None:
            return []
        reg = getattr(self._session, "_skill_registry", None)
        if reg is None:
            return []
        matches: list[tuple[str, str, bool]] = []
        for skill in reg.list_all():
            if prefix and not _fuzzy_match(prefix.lower(), skill.name.lower()):
                continue
            tag = " (loaded)" if skill.loaded else ""
            matches.append((skill.name, f"{skill.scope}{tag}", False))
        return matches

    def _complete_prompt(self, prefix: str) -> list[tuple[str, str, bool]]:
        """Complete prompt identifiers for the prompt prefix."""
        from taui.self_edit.inventory import list_items

        wd = self._config.working_dir
        try:
            prompts = (
                list_items(wd, "prompts", "project")
                + list_items(wd, "prompts", "global")
            )
        except Exception:
            return []
        matches: list[tuple[str, str, bool]] = []
        for p in prompts:
            label = getattr(p, "label", "") or ""
            summary = getattr(p, "summary", "") or ""
            if prefix and not _fuzzy_match(prefix.lower(), label.lower()):
                continue
            matches.append((label, summary[:50], False))
        return matches

    def _ensure_at_completer(self):
        """Return the cached AtCompleter for the current working directory."""
        from taui.tui.widgets.at_completer import AtCompleter

        existing = getattr(self, "_at_completer_inst", None)
        root = self._config.working_dir
        if existing is None or existing._root != root:
            existing = AtCompleter(root)
            self._at_completer_inst = existing
        return existing

    def _apply_default_agent_profile(self) -> None:
        """Apply DEF as the normal-mode default when starting a fresh session."""
        if self._session is None or not all(
            hasattr(self._session, name)
            for name in ("_registry", "_executor", "_provider", "_stream")
        ):
            return
        try:
            profile = SelfEditStore(self._config.working_dir).load_agents().get("DEF")
        except Exception:
            profile = None
        if profile is not None:
            self._apply_self_edit_profile(profile)

    def _apply_default_agent_profile_id(self) -> None:
        """Set the agent_id from DEF profile without replacing the loop."""
        if self._session is None:
            return
        try:
            profile = SelfEditStore(self._config.working_dir).load_agents().get("DEF")
        except Exception:
            profile = None
        if profile is not None:
            self._session._loop.agent_id = profile.id

    def _reapply_agent_profile(self, agent_id: str) -> None:
        """Re-apply a saved agent profile by id — used after new_session
        replaces the loop and drops the agent's prompt/tools/id."""
        if not agent_id or self._session is None:
            return
        try:
            profile = SelfEditStore(self._config.working_dir).load_agents().get(
                agent_id.upper()
            )
        except Exception:
            return
        if profile is not None:
            self._apply_self_edit_profile(profile)

    async def _begin_new_session(self) -> None:
        """Tear down any in-flight agent turn for the active session.
        Silences the current loop's callbacks first, then cancels the worker
        and resets TUI streaming state — without this, a mid-turn /new can
        leak streaming text, tool widgets, and 'Request cancelled.' notices
        into the fresh chat log."""
        state = self._sessions.active
        if state is None:
            return
        session = state.session

        old_loop = session._loop
        old_loop._on_tool_call = None
        old_loop._on_tool_result = None
        old_loop._on_approval = None
        old_loop._on_text = None
        old_loop._on_text_delta = None
        old_loop._on_reasoning_delta = None
        old_loop._on_questions_batch = None
        old_loop._on_compact = None
        llm = getattr(old_loop, "_llm", None)
        if llm is not None:
            llm.on_text_delta = None
            llm.on_reasoning_delta = None

        if state.approval_ctrl.has_active_panel():
            state.approval_ctrl.cancel_active_panel()
        state.approval_ctrl.cancel_active_approval()

        if state.is_processing:
            state.queued.clear()
            old_loop._steering_queue.clear()
            # Cancel only this session's workers
            sid = state.session_id
            for worker in list(self.workers):
                if worker.group == f"send-{sid}":
                    worker.cancel()
            for worker in list(self.workers):
                if worker.group == f"send-{sid}":
                    try:
                        await worker.wait()
                    except Exception:
                        pass
            if state.tool_ctrl is not None:
                await state.tool_ctrl.cancel_active("Cancelled")
            self._set_busy(False, state)

        state.current_response = None
        self._flush_and_detach_reasoning(state)
        state.streamed_text = False
        state.reply_footer = None
        state.pending_indicators.clear()
        state.context_banner_shown = False
        state.tool_ctrl.reset()

        try:
            self.query_one(ActivityProgress).stop()
        except NoMatches:
            pass

    def _cycle_agent_profile(self) -> None:
        """Activate the next available agent profile by ID."""
        if self._session is None:
            return
        agents = SelfEditStore(self._config.working_dir).load_agents()
        profiles = sorted(
            (p for p in agents.values() if not p.subagent_only),
            key=lambda item: item.id,
        )
        if not profiles:
            return
        active_id = str(getattr(self._session._loop, "agent_id", "") or "").upper()
        active_index = next(
            (index for index, profile in enumerate(profiles) if profile.id == active_id),
            -1,
        )
        next_profile = profiles[(active_index + 1) % len(profiles)]
        self._apply_self_edit_profile(next_profile)

    # ── Info bar ──────────────────────────────────────────────────────

    def _set_terminal_title(self, title: str | None = None) -> None:
        """Set the terminal window/tab title via ANSI escape.

        Textual redirects stdout and uses stderr for terminal I/O, so we write
        the escape sequence through the app driver when available, falling back
        to ``sys.__stderr__``.

        The terminal already shows its own app name (Ghostty, iTerm2, …) in
        the tab decoration, and macOS notifications echo this title, so we
        drop the "taui — " prefix and use the session description alone —
        that avoids "taui · X / taui — Y" duplication in OS banners.
        """
        import sys

        if title is None:
            # Derive from session description
            name = ""
            if self._session:
                name = str(getattr(self._session, "description", "") or "")
            title = name or "taui"
        escape = f"\033]0;{title}\007"
        try:
            driver = getattr(self, "_driver", None)
            if driver is not None and hasattr(driver, "write"):
                driver.write(escape)
            elif sys.__stderr__ is not None:
                sys.__stderr__.write(escape)
                sys.__stderr__.flush()
        except Exception:
            pass

    def _update_status(self) -> None:
        if not self._session:
            return
        info_bar = self.query_one(InfoBar)
        tokens = estimate_total_tokens(self._session._loop._messages)
        wt_handle = getattr(self._session, "worktree", None)
        info_bar.update_info(
            provider=self._session.provider_name,
            model=self._session.model_name,
            variant=self._session.model_variant,
            tokens=tokens,
            max_tokens=DEFAULT_MAX_INPUT_TOKENS,
            extensions_mode=self._session.extensions_mode,
            agent_id=str(getattr(self._session._loop, "agent_id", "") or ""),
            worktree_branch=wt_handle.branch if wt_handle else "",
        )
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.self_edit_mode = self._session.self_edit_mode
        except Exception:
            pass
        self._refresh_command_completions()
        self._refresh_sidebars_if_visible()
        self._set_terminal_title()

    def _refresh_sidebars_if_visible(self) -> None:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        try:
            info_sidebar = self.query_one(SessionInfoSidebar)
            if info_sidebar.has_class("visible"):
                self._refresh_info_sidebar()
        except NoMatches:
            pass
        try:
            sidebar = self.query_one(Sidebar)
            if sidebar.has_class("visible"):
                self.run_worker(
                    self._refresh_sidebar_sessions(),
                    name="refresh_sidebar_sessions",
                    exclusive=True,
                )
        except NoMatches:
            pass

    # ── Agent callbacks ───────────────────────────────────────────────

    def _wire_callbacks(self) -> None:
        state = self._sessions.active
        assert state is not None
        session = state.session
        assert session is not None
        loop = session._loop
        sid = state.session_id

        loop._on_tool_call = state.tool_ctrl.on_tool_call
        loop._on_tool_result = state.tool_ctrl.on_tool_result
        loop._on_text = self._on_text
        loop._on_text_delta = lambda frag: self._on_text_delta_sync(frag, session_id=sid)
        loop._on_reasoning_delta = (
            lambda frag: self._on_reasoning_delta_sync(frag, session_id=sid)
        )
        loop._on_approval = state.approval_ctrl.on_approval
        loop._on_questions_batch = state.approval_ctrl.on_questions_batch
        loop._on_compact = lambda r, b, a: self._on_compact_sync(r, b, a, session_id=sid)

        # Notify the TUI when the agent's prompt/tools/policy change so the
        # rendered context banner can be re-rendered. Idempotent per session —
        # the session keeps a callback list, and re-wiring after a loop swap
        # would otherwise stack duplicates.
        if not state.config_listener_wired:
            session.add_config_change_listener(
                lambda: self.post_message(AgentConfigChanged(session_id=sid))
            )
            state.config_listener_wired = True

        # Wire sub-agent callbacks so child tool calls are visible in the TUI
        try:
            from taui.tools.builtins.sub_agent import SubAgentTool

            registry = getattr(session, "_registry", None)
            if registry is not None:
                sub_agent = registry.get("sub_agent")
                if isinstance(sub_agent, SubAgentTool):
                    sub_agent._on_tool_call = state.tool_ctrl.on_tool_call
                    sub_agent._on_tool_result = state.tool_ctrl.on_tool_result
        except (ValueError, ImportError):
            pass

    def _on_text_delta_sync(self, fragment: str, *, session_id: str = "") -> None:
        """Handle real-time streaming token from the LLM provider."""
        state = self._sessions.get(session_id) if session_id else self._sessions.active
        if state is not None:
            state.streamed_text = True
        self.post_message(StreamTextDelta(fragment, session_id=session_id))

    def _on_reasoning_delta_sync(
        self, fragment: str, *, session_id: str = "",
    ) -> None:
        """Handle real-time streaming reasoning token from the LLM provider."""
        self.post_message(StreamReasoningDelta(fragment, session_id=session_id))

    async def _on_text(self, text: str) -> None:
        """Handle full text after turn — only used if no streaming occurred."""
        state = self._sessions.active
        if state is None or not state.streamed_text:
            self.post_message(StreamTextDelta(text))

    def _on_compact_sync(
        self, removed: int, before: int, after: int, *, session_id: str = "",
    ) -> None:
        """Handle auto-compaction notification from the agent loop."""
        self.post_message(
            CompactionOccurred(removed, before, after, session_id=session_id)
        )

    # ── Tool event handlers ───────────────────────────────────────────

    @on(CompactionOccurred)
    async def handle_compaction(self, event: CompactionOccurred) -> None:
        chat_log = self._get_active_chat_log()
        msg = (
            f"Context auto-compacted: {event.removed} messages removed, "
            f"tokens {event.before_tokens:,} → {event.after_tokens:,}"
        )
        await chat_log.mount(Static(f"[dim]{msg}[/dim]", markup=True))
        chat_log.scroll_end()

    @on(ToolStarted)
    async def handle_tool_started(self, event: ToolStarted) -> None:
        st = (
            self._sessions.get(event.session_id)
            if event.session_id
            else self._sessions.active
        )
        if st is not None and st.tool_ctrl is not None:
            await st.tool_ctrl.handle_tool_started(event)

    @on(ToolEnded)
    async def handle_tool_ended(self, event: ToolEnded) -> None:
        st = (
            self._sessions.get(event.session_id)
            if event.session_id
            else self._sessions.active
        )
        if st is not None and st.tool_ctrl is not None:
            await st.tool_ctrl.handle_tool_ended(event)

    @on(InfoBar.AgentBadgeClicked)
    def handle_agent_badge_clicked(
        self, event: InfoBar.AgentBadgeClicked | None = None
    ) -> None:
        self._open_agent_picker_inline()

    @on(InfoBar.ModelBadgeClicked)
    def handle_model_badge_clicked(self, event: InfoBar.ModelBadgeClicked) -> None:
        self._open_model_picker_inline()

    @on(InfoBar.VariantBadgeClicked)
    def handle_variant_badge_clicked(self, event: InfoBar.VariantBadgeClicked) -> None:
        self._open_variant_picker()

    @on(InfoBar.ContextBadgeClicked)
    def handle_context_badge_clicked(self, event: InfoBar.ContextBadgeClicked) -> None:
        self._open_context_tree()

    async def _load_and_show_sessions(self) -> None:
        self._open_sessions_sidebar()

    def _open_palette(self, prefilter: str = "") -> None:
        """Open the command palette. `prefilter` pre-fills the search input."""
        if CommandPalette.is_open(self):
            return
        palette = CommandPalette(id="--command-palette")
        self.push_screen(palette)
        if not prefilter:
            return

        def _fill() -> None:
            try:
                inp = self.screen.query_one(CommandInput)
            except NoMatches:
                return
            inp.value = prefilter
            inp.cursor_position = len(prefilter)

        self.call_after_refresh(_fill)

    def _apply_selected_skill(self, name: str | None) -> None:
        if not name:
            return
        skill_reg = getattr(self._session, "_skill_registry", None)
        if skill_reg is None:
            return
        skill = skill_reg.get(name)
        if skill is None:
            return
        if skill.loaded:
            skill.loaded = False
            self.notify(f"Skill '{name}' unloaded.")
        else:
            try:
                content = skill.load_content()
            except Exception as exc:
                self.notify(f"Failed to load skill '{name}': {exc}", severity="error")
                return
            from taui.agent.loop import Message
            self._session._loop._messages.append(
                Message(role="system", content=f"[Skill: {name}]\n\n{content}")
            )
            skill.loaded = True
            self.notify(f"Skill '{name}' loaded.")

    def _lookup_prompt_body(self, identifier: str) -> str | None:
        """Return the body of a prompt with the given identifier, or None."""
        from taui.self_edit.inventory import list_items

        wd = self._config.working_dir
        try:
            items = (
                list_items(wd, "prompts", "project")
                + list_items(wd, "prompts", "global")
            )
        except Exception:
            return None
        for item in items:
            if item.identifier == identifier:
                return item.body
        return None

    async def _apply_selected_prompt(self, identifier: str | None) -> None:
        if not identifier:
            return
        body = self._lookup_prompt_body(identifier)
        if body is None:
            self.notify(f"Prompt '{identifier}' not found.", severity="error")
            return
        await self._submit_generated_prompt(body)

    def _refill_input(self, text: str) -> None:
        """Re-fill the chat input with *text* after a command cleared it."""
        try:
            ci = self.query_one("#chat-input", ChatInput)
            ci.clear()
            ci.insert(text)
        except Exception:
            pass

    def _open_context_tree(self) -> None:
        if self._session is None:
            return
        self.push_screen(ContextBreakdownScreen(self._session._loop._messages))

    _ALLOWED_THEMES = {"taui-dark", "taui-light"}

    def _open_theme_picker(self) -> None:
        """Open the modal theme picker (curated taui themes only)."""
        current = str(self.theme or "taui-dark")
        self.push_screen(
            ThemePickerScreen(current=current),
            self._apply_theme,
        )

    def _open_model_picker_inline(self) -> None:
        """Show the inline Info2 model picker without clobbering chat input."""
        from taui.llm_provider.models import list_models

        if self._session is not None:
            provider = self._session.config.provider
            current = self._session.model_name or self._session.config.model or ""
        else:
            provider = self._config.provider
            current = self._config.model or ""

        models = list_models(provider) if provider else []
        if not models:
            cmd_pfx = self._config.prefixes.get("command", "/")
            self._refill_input(f"{cmd_pfx}model ")
            return

        try:
            info2 = self.query_one(Info2)
        except Exception:
            return
        info2.show_models(models, current=current)

    def _open_agent_picker_inline(self) -> None:
        """Show the inline Info2 agent picker without clobbering chat input."""
        agents = SelfEditStore(self._config.working_dir).load_agents()
        profiles = sorted(
            (p for p in agents.values() if not p.subagent_only),
            key=lambda item: item.id,
        )
        if not profiles:
            cmd_pfx = self._config.prefixes.get("command", "/")
            self._refill_input(f"{cmd_pfx}agents ")
            return

        current = ""
        if self._session is not None:
            current = str(getattr(self._session._loop, "agent_id", "") or "")

        try:
            info2 = self.query_one(Info2)
        except Exception:
            return
        info2.show_agents(profiles, current=current)

    def _open_variant_picker(self) -> None:
        """Open the modal model-variant picker, scoped to the current model."""
        from taui.llm_provider.models import get_model_variants

        if self._session is not None:
            current = self._session.model_variant or ""
            provider = self._session.provider_name
            model = self._session.model_name
        else:
            current = self._config.model_variant or ""
            provider = self._config.provider
            model = self._config.model

        variants = get_model_variants(provider, model) if model else []
        if not variants:
            self.notify(
                f"{model or 'Current model'} has no reasoning variants.",
                severity="information",
            )
            return

        self.push_screen(
            VariantPickerScreen(variants, current=current, model=model),
            self._apply_variant,
        )

    def _apply_variant(self, variant: str | None) -> None:
        if variant is None:
            return
        if self._session is not None:
            self._session.config.model_variant = variant
            try:
                self._session._loop._model_variant = variant
            except Exception:
                pass
        self._config.model_variant = variant
        self._update_status()

    def _apply_theme(self, theme: str | None) -> None:
        if not theme:
            return
        if theme not in self._ALLOWED_THEMES:
            self.notify(
                f"Theme '{theme}' is not supported yet.",
                severity="warning",
            )
            return
        try:
            self.theme = theme
        except Exception as exc:
            self.notify(f"Failed to switch theme: {exc}", severity="error")

    def _open_sessions_sidebar(self) -> None:
        """Open the left sidebar on the sessions tab."""
        try:
            sidebar = self.query_one(Sidebar)
        except NoMatches:
            return
        if not sidebar.has_class("visible"):
            sidebar.toggle()
        sidebar.action_show_tab("sessions")
        self.run_worker(
            self._refresh_sidebar_sessions(),
            name="refresh_sidebar_sessions",
            exclusive=True,
        )

    def _apply_selected_agent(self, selected: str | None) -> None:
        if selected is None:
            return
        profile = SelfEditStore(self._config.working_dir).load_agents().get(
            selected.upper()
        )
        if profile is None:
            return
        self._apply_self_edit_profile(profile)
        self._update_status()

    def _apply_selected_model(self, selected: str | None) -> None:
        if selected:
            if self._session is None:
                return
            self._session.config.model = selected
            self._session._loop._model = selected
            self._update_status()
            # Persist model choice to session metadata
            async def _persist() -> None:
                await self._session._store.update_session(
                    self._session.session_id, model=selected
                )
            try:
                self.run_worker(_persist(), exclusive=False)
            except Exception:
                pass
            # Remember as last-used model for this provider
            try:
                from taui.llm_provider.config import save_last_model
                save_last_model(self._session.config.provider, selected)
            except Exception:
                pass

    @on(Info2.ModelSelected)
    def handle_info2_model_selected(self, event: Info2.ModelSelected) -> None:
        self._apply_selected_model(event.model_id)

    @on(Info2.AgentSelected)
    def handle_info2_agent_selected(self, event: Info2.AgentSelected) -> None:
        self._apply_selected_agent(event.agent_id)

    @on(Info2.SessionSelected)
    def handle_info2_session_selected(self, event: Info2.SessionSelected) -> None:
        self.run_worker(
            self._resume_session(event.session_id),
            name="session_resume",
            exclusive=True,
        )

    @on(Info2.SkillSelected)
    def handle_info2_skill_selected(self, event: Info2.SkillSelected) -> None:
        self._apply_selected_skill(event.skill_name)

    @on(Info2.PromptSelected)
    async def handle_info2_prompt_selected(self, event: Info2.PromptSelected) -> None:
        await self._apply_selected_prompt(event.prompt_id)

    # ── Streaming text handlers ───────────────────────────────────────

    @on(StreamTextDelta)
    async def handle_stream_text(self, event: StreamTextDelta) -> None:
        """Handle incoming text deltas — stream into AgentResponse widget."""
        st = (
            self._sessions.get(event.session_id)
            if event.session_id
            else self._sessions.active
        )
        if st is None:
            return
        # Finalize reasoning block when regular text starts arriving
        self._flush_and_detach_reasoning(st)
        if st.current_response is None:
            st.current_response = AgentResponse()
            await self._mount_in_reply(st.current_response, state=st)
        await st.current_response.append_text(event.text)
        self._smart_scroll()

    @on(StreamReasoningDelta)
    async def handle_stream_reasoning(self, event: StreamReasoningDelta) -> None:
        """Handle incoming reasoning deltas — stream into a dimmed Static widget."""
        st = (
            self._sessions.get(event.session_id)
            if event.session_id
            else self._sessions.active
        )
        if st is None:
            return
        st.reasoning_buf += event.text
        if st.current_reasoning is None:
            st.current_reasoning = Static(
                f"[dim italic]{escape(st.reasoning_buf)}[/dim italic]",
                classes="reasoning-text",
                markup=True,
            )
            await self._mount_in_reply(st.current_reasoning, state=st)
            st._reasoning_render_pending = False
        elif not st._reasoning_render_pending:
            st._reasoning_render_pending = True

            def _flush_reasoning() -> None:
                st._reasoning_render_pending = False
                if st.current_reasoning is not None:
                    st.current_reasoning.update(
                        f"[dim italic]{escape(st.reasoning_buf)}[/dim italic]"
                    )

            self.call_after_refresh(_flush_reasoning)
        self._smart_scroll()

    # ── Input handling ────────────────────────────────────────────────

    @on(ChatInput.Submitted)
    async def handle_input(self, event: ChatInput.Submitted) -> None:
        text = event.value
        images = event.images or None

        if text.startswith(self._config.prefixes.get("command", "/")):
            await self._handle_command(text)
            return

        skills_pfx = self._config.prefixes.get("skills", "!")
        if text.startswith(skills_pfx):
            name = text[len(skills_pfx):].strip()
            if name:
                self._apply_selected_skill(name)
            else:
                self._refill_input(skills_pfx)
            return

        prompts_pfx = self._config.prefixes.get("prompts", "#")
        if text.startswith(prompts_pfx):
            identifier = text[len(prompts_pfx):].strip()
            if not identifier:
                self._refill_input(prompts_pfx)
                return
            # Only intercept when the identifier matches a known prompt;
            # otherwise let the text (e.g. a Markdown heading) flow through
            # as a normal user message.
            if self._lookup_prompt_body(identifier) is not None:
                await self._apply_selected_prompt(identifier)
                return

        if self._session is None:
            chat_log = self._get_active_chat_log()
            await chat_log.mount(
                Static(
                    "[yellow]No session is active. Fix auth/network access "
                    "and restart, or run /login.[/yellow]",
                    markup=True,
                )
            )
            self._smart_scroll()
            return

        # Save to history
        self._save_to_history(text)

        # Expand @file references (may add images)
        text, extra_images = self._expand_file_refs(text)
        if extra_images:
            images = (images or []) + extra_images
        # Replace [N] bar markers with chat-log / LLM-side expansions.
        chat_text, send_text, images = self._render_bar_attachments(text, images)

        if self._is_processing:
            if event.queue:
                # Alt+Enter while busy → queue
                self._queued.append((send_text, images))
                self._pending_indicators.append(("q", send_text))
                await self._show_indicator("q", send_text)
            else:
                # Enter while busy → steer
                assert self._session is not None
                self._session._loop.steer(send_text)
                self._pending_indicators.append(("s", send_text))
                await self._show_indicator("s", send_text)
            return

        # Normal send
        chat_log = self._get_active_chat_log()

        # Show context banner before the very first message
        await self._maybe_show_context_banner(chat_log)

        await self._begin_turn(chat_text, "", chat_log=chat_log)
        # Clear the attachments bar (and pending file/folder/paste lists) after submit
        self.query_one(AttachmentsBar).clear_all()
        self._pending_files.clear()
        self._pending_folders.clear()
        try:
            self.query_one(ChatInput).clear_pastes()
        except Exception:
            pass
        # Submitting is an explicit intent to see the result — re-arm anchor.
        self._snap_to_bottom()
        self._send_and_drain(send_text, images)

    async def _submit_generated_prompt(
        self,
        text: str,
        *,
        tool_names: list[str] | None = None,
    ) -> None:
        """Submit a prompt produced by a slash command as a normal user turn."""
        if self._session is None:
            chat_log = self._get_active_chat_log()
            await chat_log.mount(Static("[yellow]No session is active.[/yellow]", markup=True))
            self._smart_scroll()
            return
        self._save_to_history(text)
        chat_log = self._get_active_chat_log()
        await self._begin_turn(text, "", chat_log=chat_log)
        self._snap_to_bottom()
        self._send_and_drain(text, tool_names=tool_names)

    @on(ChatInput.AgentCycleRequested)
    async def handle_agent_cycle_requested(
        self,
        event: ChatInput.AgentCycleRequested,
    ) -> None:
        self._cycle_agent_profile()

    @on(ChatInput.ScopeCycleRequested)
    async def handle_scope_cycle_requested(
        self,
        event: ChatInput.ScopeCycleRequested,
    ) -> None:
        if self._session is None or not self._session.self_edit_mode:
            return
        new_scope = await self._session.switch_self_edit_scope()
        chat_log = self._get_active_chat_log()
        await chat_log.mount(
            Static(self._self_edit_scope_line(new_scope), markup=True)
        )
        self._update_status()

    @on(ChatInput.AtAttachRequested)
    async def handle_at_attach_requested(
        self,
        event: ChatInput.AtAttachRequested,
    ) -> None:
        """Add a file/folder picked via `@`-autocomplete as a pill.

        The pill carries the absolute path; on submit the same expansion logic
        used for sidebar-picked attachments folds the contents into the prompt.
        """
        root = self._config.working_dir
        path = (root / event.path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            # Refuse paths that escape the project root.
            return
        bar = self.query_one(AttachmentsBar)
        chat_input = self.query_one(ChatInput)
        if event.is_dir:
            if not path.is_dir():
                return
            if bar.find_index(kind="folder", data=str(path)) >= 0:
                return
            idx = bar.add(str(path), kind="folder", name=path.name)
            self._pending_folders.append(path)
            chat_input.insert_attachment_marker(idx + 1)
        else:
            if not path.is_file():
                return
            if bar.find_index(kind="file", data=str(path)) >= 0:
                return
            idx = bar.add(str(path), kind="file", name=path.name)
            self._pending_files.append(path)
            chat_input.insert_attachment_marker(idx + 1)

    @on(ChatInput.CommandInvoked)
    async def handle_command_invoked(
        self,
        event: ChatInput.CommandInvoked,
    ) -> None:
        """Run a slash command picked via mid-sentence alt+/ completion."""
        await self._handle_command(event.command)

    @on(ChatInput.ImageAttached)
    async def handle_image_attached(
        self,
        event: ChatInput.ImageAttached,
    ) -> None:
        """Add a pill and an inline ``[N]`` marker for a newly attached image."""
        chat_input = self.query_one(ChatInput)
        bar = self.query_one(AttachmentsBar)
        if event.data_url and bar.find_index(kind="image", data=event.data_url) >= 0:
            return
        idx = bar.add(event.data_url, kind="image")
        chat_input.insert_attachment_marker(idx + 1)

    @on(ChatInput.PasteAttached)
    async def handle_paste_attached(
        self,
        event: ChatInput.PasteAttached,
    ) -> None:
        """Add a paste pill and an inline ``[N]`` marker for a captured paste."""
        bar = self.query_one(AttachmentsBar)
        chat_input = self.query_one(ChatInput)
        idx = bar.add(event.text, kind="paste")
        chat_input.insert_attachment_marker(idx + 1)

    @on(AttachmentsBar.PasteOpened)
    async def handle_paste_opened(
        self,
        event: AttachmentsBar.PasteOpened,
    ) -> None:
        """Open the editor modal for a paste pill."""
        original = event.data

        def _on_close(result: PasteResult | None) -> None:
            if result is None:
                return
            chat_input = self.query_one(ChatInput)
            bar = self.query_one(AttachmentsBar)
            bar_idx = bar.find_index(kind="paste", data=original)
            try:
                input_idx = chat_input.pending_pastes.index(original)
            except ValueError:
                input_idx = -1

            if result.action == "save":
                if not result.text:
                    if bar_idx >= 0:
                        bar.remove(bar_idx)
                        chat_input.remove_attachment_marker(bar_idx + 1)
                    if input_idx >= 0:
                        chat_input.pop_paste(input_idx)
                    return
                if input_idx >= 0:
                    chat_input.update_paste(input_idx, result.text)
                if bar_idx >= 0:
                    bar.update_data(bar_idx, result.text)
                return

            # action == "insert"
            if input_idx >= 0:
                chat_input.pop_paste(input_idx)
            if bar_idx >= 0:
                bar.remove(bar_idx)
                chat_input.remove_attachment_marker(bar_idx + 1)
            if result.text:
                chat_input.insert(result.text)
                chat_input.focus()

        self.push_screen(
            PastedContentScreen(original, index=event.index), _on_close
        )

    @on(AttachmentsBar.Cleared)
    async def handle_attachment_cleared(
        self,
        event: AttachmentsBar.Cleared,
    ) -> None:
        """Sync the chat-input image buffer / app file buffer with the bar.

        Also strips the matching ``[N]`` marker from the chat input and
        shifts higher-numbered markers down by one so they stay aligned
        with the bar's new numbering.
        """
        chat_input = self.query_one(ChatInput)
        if event.kind == "file":
            try:
                self._pending_files.remove(Path(event.data))
            except ValueError:
                pass
        elif event.kind == "folder":
            try:
                self._pending_folders.remove(Path(event.data))
            except ValueError:
                pass
        elif event.kind == "paste":
            chat_input.remove_paste_by_value(event.data)
        else:  # image
            if event.data and event.data in chat_input._pending_images:
                chat_input._pending_images.remove(event.data)
            elif 0 <= event.index < len(chat_input._pending_images):
                chat_input._pending_images.pop(event.index)
        chat_input.remove_attachment_marker(event.index + 1)

    @on(Sidebar.FileToggleRequested)
    async def handle_sidebar_file_toggle(
        self,
        event: Sidebar.FileToggleRequested,
    ) -> None:
        """Toggle a file picked in the sidebar's Files tab as an attachment.

        Clicking a fresh file adds a pill; clicking the same file again
        removes that pill (so re-clicking is a deselect, like a checkbox).
        """
        path = event.path.resolve()
        bar = self.query_one(AttachmentsBar)
        chat_input = self.query_one(ChatInput)
        path_str = str(path)
        existing = bar.find_index(kind="file", data=path_str)
        if existing >= 0:
            bar.remove(existing)
            try:
                self._pending_files.remove(path)
            except ValueError:
                pass
            chat_input.remove_attachment_marker(existing + 1)
            return
        if not path.is_file():
            return
        idx = bar.add(path_str, kind="file", name=path.name)
        self._pending_files.append(path)
        chat_input.insert_attachment_marker(idx + 1)

    @on(Sidebar.FolderToggleRequested)
    async def handle_sidebar_folder_toggle(
        self,
        event: Sidebar.FolderToggleRequested,
    ) -> None:
        """Toggle a folder picked in the sidebar's Files tab as an attachment."""
        path = event.path.resolve()
        bar = self.query_one(AttachmentsBar)
        chat_input = self.query_one(ChatInput)
        path_str = str(path)
        existing = bar.find_index(kind="folder", data=path_str)
        if existing >= 0:
            bar.remove(existing)
            try:
                self._pending_folders.remove(path)
            except ValueError:
                pass
            chat_input.remove_attachment_marker(existing + 1)
            return
        if not path.is_dir():
            return
        idx = bar.add(path_str, kind="folder", name=path.name)
        self._pending_folders.append(path)
        chat_input.insert_attachment_marker(idx + 1)

    @on(ChatInput.InputCleared)
    async def handle_input_cleared(self, event: ChatInput.InputCleared) -> None:
        """Clear attachments bar when user double-presses Escape."""
        self.query_one(AttachmentsBar).clear_all()
        self._pending_files.clear()
        self._pending_folders.clear()
        try:
            self.query_one(ChatInput).clear_pastes()
        except Exception:
            pass

    @on(ChatInput.CancelRequested)
    async def handle_cancel_requested(
        self, event: ChatInput.CancelRequested
    ) -> None:
        """Escape on empty input cancels streaming like Ctrl+C."""
        await self.action_cancel_request()

    async def _show_indicator(self, mode: str, text: str) -> None:
        """Show a steer/queue indicator in the chat log."""
        if mode == "s":
            widget = Static(
                f"[dim]  s> {escape(text)}[/dim]",
                classes="steer-indicator",
                markup=True,
            )
        else:
            widget = Static(
                f"[#f5a524]  q> {escape(text)}[/#f5a524]",
                classes="queue-indicator",
                markup=True,
            )
        await self._mount_in_reply(widget)
        self._smart_scroll()


    # ── Context banner ─────────────────────────────────────────────────

    def _build_context_banner_markup(self) -> str:
        """Render the context-start block (system prompt + tool list) for the active session.

        This is referred to as the "context-start" banner. Tools are shown as
        a 3-column table: active tools (in the loop's effective registry) are
        light gray; tools that are available but not active for the current
        variant are dark gray.
        """
        if self._session is None:
            return ""

        parts: list[str] = []

        sp = getattr(self._session, "_system_prompt", "") or ""
        if self._session.self_edit_mode:
            sp = getattr(self._session, "_self_edit_prompt", "") or sp
        elif getattr(self._session, "extensions_mode", False):
            sp = getattr(self._session, "_extensions_prompt", "") or sp
        agent_id = str(getattr(self._session._loop, "agent_id", "") or "")
        agent_clr = _agent_color(agent_id) if agent_id else "#58a6ff"
        bg_clr = "#070707" if self.theme == TAUI_DARK.name else "#ffffff"
        label_style = f"bold {bg_clr} on {agent_clr}"

        if sp:
            lines = sp.splitlines()
            preview = lines[:100]
            if len(lines) > 100:
                preview.append("...")
            safe_sp = "\n".join(preview).replace("[", "\\[")
            parts.append(
                f"[{label_style}]System prompt[/{label_style}]\n[dim]{safe_sp}[/dim]"
            )

        available: list[str] = []
        if hasattr(self._session, "_registry"):
            available = list(getattr(self._session._registry, "names", []) or [])

        active: set[str] = set()
        try:
            active = set(self._session._loop._executor.registry.names)
        except AttributeError:
            active = set(available)

        if available:
            if parts:
                parts.append("")
            parts.append(f"[{label_style}]Tools[/{label_style}]")
            parts.append(_render_tools_table(available, active, columns=3))
            parts.append("")

        return "\n".join(parts)

    async def _maybe_show_context_banner(self, chat_log) -> None:
        """Show system prompt + tool list once, before the first user message."""
        if self._context_banner_shown or self._session is None:
            return
        self._context_banner_shown = True

        banner = self._build_context_banner_markup()
        if banner:
            await chat_log.mount(
                Static(banner, classes="context-banner", markup=True)
            )

    def _refresh_context_banner(self, session_id: str = "") -> None:
        """Re-render the context-start banner when agent config changes."""
        state = self._sessions.get(session_id) if session_id else self._sessions.active
        if state is None or state.session is None:
            return
        # Only the active session's banner is mounted in the visible chat log;
        # for inactive sessions, clear the shown flag so it re-renders fresh
        # the next time we switch to it.
        if state is not self._sessions.active:
            state.context_banner_shown = False
            return
        try:
            chat_log = self._get_active_chat_log()
            banner_widget = chat_log.query_one(".context-banner", Static)
        except (NoMatches, Exception):
            return
        markup = self._build_context_banner_markup()
        if markup:
            banner_widget.update(markup)

    @on(AgentConfigChanged)
    def handle_agent_config_changed(self, event: AgentConfigChanged) -> None:
        self._refresh_context_banner(event.session_id)
        self._update_status()

    # ── Send message and drain queue ──────────────────────────────────

    def _send_and_drain(
        self,
        text: str,
        images: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> None:
        """Launch the send worker for the active session.

        Each session gets its own exclusive worker group so parallel sessions
        don't cancel each other's workers.
        """
        state = self._sessions.active
        assert state is not None
        sid = state.session_id
        self.run_worker(
            self._do_send_and_drain(state, text, images, tool_names),
            name=f"send-{sid}",
            group=f"send-{sid}",
            exclusive=True,
        )

    async def _do_send_and_drain(
        self,
        state: SessionState,
        text: str,
        images: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> None:
        state.is_processing = True
        self._set_busy(True, state)

        try:
            await self._do_send(text, images=images, tool_names=tool_names,
                                state=state)

            # Drain queued messages
            while state.queued:
                msg, queued_images = state.queued.pop(0)
                chat_log = state.chat_log or self._get_active_chat_log()
                await chat_log.mount(
                    Static(
                        "[dim]  → processing follow-up[/dim]",
                        markup=True,
                    )
                )
                await chat_log.mount(
                    Static(
                        f"[bold #e6edf3]{escape(msg)}[/bold #e6edf3]",
                        classes="user-message",
                        markup=True,
                    )
                )
                await self._do_send(msg, images=queued_images, state=state)
        finally:
            state.is_processing = False
            self._set_busy(False, state)
            self._refresh_tab_bar()
            # Agent finished — let the user know if they tabbed away.
            # macOS notifications stack three lines:
            #   header  → OSC 777 title (small, top)
            #   title   → terminal window title (bold, middle)
            #   body    → OSC 777 body (regular, bottom)
            # The window title already carries the session description, so
            # the OSC 777 body should be a status string (not the same
            # description again). Use the header to brand the app.
            try:
                agent_id = ""
                session = state.session
                if session is not None:
                    agent_id = str(getattr(session._loop, "agent_id", "") or "")
                title = f"TAUI · {agent_id}" if agent_id else "TAUI"
                body = "Agent finished"
                # In-app toast only fires for background sessions — the
                # user is already looking at the active tab, so a banner
                # there would be noise.
                is_active = self._sessions.active is state
                self._notify_user(
                    title, body, kind="done", from_active_session=is_active
                )
            except Exception:
                pass

    async def _do_send(
        self,
        text: str,
        *,
        images: list[str] | None = None,
        tool_names: list[str] | None = None,
        state: SessionState | None = None,
    ) -> None:
        """Send a single message and display the result."""
        # Use provided state or fall back to active
        st = state or self._sessions.active
        assert st is not None
        session = st.session

        progress = self.query_one(ActivityProgress)
        agent_id = str(getattr(session._loop, "agent_id", "") or "")
        progress.set_active_style(_agent_color(agent_id) if agent_id else "#3fb950")
        progress.start()

        st.tool_ctrl.reset_section()
        st.current_response = None
        self._flush_and_detach_reasoning(st)
        st.streamed_text = False
        st.reply_footer = None
        await self._begin_reply_footer(st)

        old_session_executor = None
        old_loop_executor = None
        try:
            if tool_names is not None:
                from taui.tools.executor import ToolExecutor

                old_session_executor = session._executor
                old_loop_executor = session._loop._executor
                available = [name for name in tool_names if name in session._registry]
                effective = ToolExecutor(
                    registry=session._registry.subset(available),
                    policy=old_loop_executor.policy,
                )
                effective._truncation_store = getattr(
                    old_loop_executor,
                    "_truncation_store",
                    None,
                )
                session._executor = effective
                session._loop._executor = effective
            import time as _time

            _send_start = _time.monotonic()
            result = await session.send(text, images=images)
            _send_elapsed = _time.monotonic() - _send_start

            if st.reply_footer is not None:
                st.reply_footer.finalize(_send_elapsed)

            # Finalize any streaming response
            await self._finalize_response(st)

            # If no streaming happened (fallback), show response as markdown
            if result.text and not st.streamed_text:
                await self._mount_in_reply(Markdown(result.text), state=st)

            # Per-turn stats for the collapsed header (tokens + tool count)
            if st.current_turn is not None:
                try:
                    usage = result.total_usage
                    total_tokens = int(
                        usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                    )
                except Exception:
                    total_tokens = 0
                if total_tokens == 0:
                    # Fallback: ~4 chars/token when the provider doesn't
                    # report usage (e.g., Copilot).
                    total_tokens = _estimate_tokens_from_text(text, result.text)
                try:
                    tool_count = len(st.current_turn.body.query(ToolStatusWidget))
                except Exception:
                    tool_count = 0
                st.current_turn.set_summary(
                    total_tokens=total_tokens,
                    tool_count=tool_count,
                    model=getattr(session._loop, "_model", ""),
                    duration_s=_send_elapsed,
                    agent_id=str(getattr(session._loop, "agent_id", "") or ""),
                )

            # Turn summary
            summary_parts: list[str] = []
            for fn in session.hooks._hooks.get("turn_summary", []):
                try:
                    extra = fn(result, session)
                    if extra:
                        summary_parts.append(str(extra))
                except Exception:
                    pass
            if summary_parts:
                summary = f"[dim]{' · '.join(summary_parts)}[/dim]"
                await self._mount_in_reply(
                    Static(summary, classes="turn-summary", markup=True),
                    state=st,
                )

            self._update_status()
            self._smart_scroll()
        except asyncio.CancelledError:
            await self._mount_in_reply(
                Static("[dim]Request cancelled.[/dim]", markup=True),
                state=st,
            )
        except Exception as exc:
            await self._mount_in_reply(
                Static(f"[red]Error: {exc}[/red]", markup=True),
                state=st,
            )
        finally:
            if old_loop_executor is not None:
                session._loop._executor = old_loop_executor
            if old_session_executor is not None:
                session._executor = old_session_executor
            progress.stop()
            st.tool_ctrl.reset_section()
            # Intentionally do NOT clear `self._reply_footer` here. Stream
            # deltas are dispatched off Textual's message queue and a few
            # can still be pending after `_session.send()` returns. Nulling
            # the ref now would cause those late deltas to fall into the
            # `footer is None` branch of `_mount_in_reply` and mount their
            # content past the footer. The next turn's `_do_send` nulls it
            # (and `_begin_reply_footer` rebuilds a fresh one) once we're
            # safely past any in-flight callbacks from the prior turn.

    def _flush_and_detach_reasoning(self, st: SessionState) -> None:
        """Flush any pending reasoning update, then detach the widget ref.

        The widget stays in the DOM with its final content — we just stop
        appending to it.  This avoids the race where a deferred
        ``call_after_refresh`` flush runs *after* the state has been
        cleared, silently dropping the last batch of reasoning text.
        """
        if st.current_reasoning is not None:
            if st.reasoning_buf:
                st.current_reasoning.update(
                    f"[dim italic]{escape(st.reasoning_buf)}[/dim italic]"
                )
            st._reasoning_render_pending = False
            st.current_reasoning = None
        st.reasoning_buf = ""

    async def _finalize_response(self, state: SessionState | None = None) -> None:
        """Finalize the current streaming response if any."""
        st = state or self._sessions.active
        if st is None:
            return
        if st.current_response:
            await st.current_response.finalize()
            st.current_response = None
            st.tool_ctrl.reset_section()
        self._flush_and_detach_reasoning(st)

    # ── Busy state management ─────────────────────────────────────────

    def _set_busy(self, busy: bool, state: SessionState | None = None) -> None:
        st = state or self._sessions.active
        if st is not None:
            st.is_processing = busy
        chat_input = self.query_one("#chat-input", ChatInput)
        # Agent is busy if *any* session is processing
        chat_input.agent_busy = self._sessions.any_processing
        if not busy:
            if st is not None:
                st.pending_indicators.clear()
            chat_input.focus()
        self._refresh_tab_bar()

    # ── Mouse auto-copy ───────────────────────────────────────────────

    def on_mouse_up(self, event) -> None:
        """Auto-copy selected text to clipboard."""
        try:
            selected = self.screen.get_selected_text()
            if selected:
                self.copy_to_clipboard(selected)
                self.notify("Copied to clipboard", timeout=1.5)
        except Exception:
            pass

    # ── Splash art ─────────────────────────────────────────────────────

    _SPLASH_ART = (
        "  .::                      .:      \n"
        "  .::                              \n"
        ".:.: .:   .::    .::  .:: .::      \n"
        "  .::   .::  .:: .::  .:: .::      \n"
        "  .::  .::   .:: .::  .:: .::      \n"
        "  .::  .::   .:: .::  .:: .::      \n"
        "   .::   .:: .:::  .::.:: .:: .:::::\n"# noqa: E501
    )

    async def _mount_splash(self, chat_log: VerticalScroll) -> None:
        """Mount the splash art widget into an empty chat log."""
        await chat_log.mount(
            Static(self._SPLASH_ART, classes="session-splash")
        )

    async def _remove_splash(self, chat_log: VerticalScroll) -> None:
        """Remove the splash art if present."""
        for widget in chat_log.query(".session-splash"):
            await widget.remove()

    # ── Per-turn container ────────────────────────────────────────────

    async def _begin_turn(
        self,
        user_text: str,
        image_note: str = "",
        *,
        chat_log: VerticalScroll | None = None,
        state: SessionState | None = None,
    ) -> TurnContainer:
        """Create and mount a new turn container, run autocollapse, return it."""
        st = state or self._sessions.active
        log = chat_log or (st.chat_log if st is not None else None) or self._get_active_chat_log()
        await self._remove_splash(log)
        turn_id = len(st.turns) if st is not None else 0
        turn = TurnContainer(user_text, image_note, turn_id=turn_id)
        if st is not None:
            st.turns.append(turn)
            st.current_turn = turn
        await log.mount(turn)
        self._autocollapse_old_turns(st)
        return turn

    def _autocollapse_old_turns(self, state: SessionState | None) -> None:
        """Keep the current turn and the immediately preceding turn expanded;
        collapse anything older. A user-stickied turn stays open."""
        if state is None or not state.turns:
            return
        keep = set(state.turns[-2:])
        for t in state.turns:
            if t in keep or t.sticky_expanded:
                t.expand()
            else:
                t.collapse()

    # ── Per-reply footer ──────────────────────────────────────────────

    async def _begin_reply_footer(self, state: SessionState | None = None) -> None:
        """Eagerly mount the per-turn footer at the start of `_do_send`.

        Doing this once, before any callbacks can fire, guarantees a single
        ReplyFooter per turn — no race window where two streaming callbacks
        both think they need to create one."""
        st = state or self._sessions.active
        if st is None:
            return
        if st.reply_footer is not None:
            return
        chat_log = st.chat_log or self._get_active_chat_log()
        agent_id = ""
        model = ""
        session = st.session
        if session is not None:
            agent_id = str(getattr(session._loop, "agent_id", "") or "")
            model = session.model_name or ""
        footer = ReplyFooter(agent_id, model)
        st.reply_footer = footer
        if st.current_turn is not None:
            await st.current_turn.body.mount(footer)
        else:
            await chat_log.mount(footer)

    async def _mount_in_reply(
        self, widget, *, state: SessionState | None = None,
    ) -> None:
        """Mount a widget into the active turn's body (above its footer).

        Falls back to the chat log when there is no active turn — that
        path is used for system banners and out-of-turn diagnostics
        which historically rendered as siblings of user messages."""
        st = state or self._sessions.active
        if st is not None and st.current_turn is not None:
            body = st.current_turn.body
            footer = st.reply_footer
            if footer is not None and footer.parent is body:
                await body.mount(widget, before=footer)
            else:
                await body.mount(widget)
            return
        if st is not None:
            chat_log = st.chat_log or self._get_active_chat_log()
            footer = st.reply_footer
        else:
            chat_log = self._get_active_chat_log()
            footer = None
        if footer is not None:
            await chat_log.mount(widget, before=footer)
        else:
            await chat_log.mount(widget)

    # ── Notifications ─────────────────────────────────────────────────

    def on_app_focus(self) -> None:
        self._window_focused = True

    def on_app_blur(self) -> None:
        self._window_focused = False

    def _notify_user(
        self,
        header: str,
        message: str,
        *,
        kind: str = "info",
        from_active_session: bool = False,
    ) -> None:
        """Surface an event to the user, in-app or via the OS.

        - When the terminal window has focus → Textual toast (`notify`),
          unless the event came from the session the user is already
          looking at (``from_active_session=True``), in which case the
          toast is suppressed — they can see it directly in the chat.
        - When the terminal is backgrounded → OSC 777 escape, which
          Ghostty / iTerm2 / WezTerm / Kitty translate into a real OS
          notification. Background sessions always notify the OS so the
          user gets pinged even if the active tab is something else.

        ``kind`` is one of {"info", "question", "done"} and gates which
        events fire based on the user's config flags.
        """
        cfg = self._config
        if not getattr(cfg, "notifications", True):
            return
        if kind == "done" and not getattr(cfg, "notify_on_turn_done", True):
            return
        if kind == "question" and not getattr(cfg, "notify_on_question", True):
            return
        # Clip the message body — system banners get truncated anyway and
        # printing huge payloads can confuse the terminal escape parser.
        body = message.replace("\n", " ").replace("\r", " ")
        if len(body) > 200:
            body = body[:197] + "…"
        head = header.replace(";", ":")
        if self._window_focused:
            if from_active_session:
                # User is already watching this session — don't pop a
                # toast that just repeats what's on screen.
                return
            try:
                self.notify(body, title=head, timeout=4.0)
            except Exception:
                pass
            return
        # Backgrounded — fall back to OSC 777 so the OS shows a banner.
        # Textual owns stdout while running, so we write the escape through
        # the active driver (or stderr as a fallback) — same pattern used by
        # _set_terminal_title.
        escape_seq = f"\x1b]777;notify;{head};{body}\x07"
        try:
            import sys

            driver = getattr(self, "_driver", None)
            if driver is not None and hasattr(driver, "write"):
                driver.write(escape_seq)
                if hasattr(driver, "flush"):
                    driver.flush()
            elif sys.__stderr__ is not None:
                sys.__stderr__.write(escape_seq)
                sys.__stderr__.flush()
        except Exception:
            pass

    # ── Smart scroll ──────────────────────────────────────────────────

    def _smart_scroll(self) -> None:
        """No-op: the chat log is anchored, so layout passes auto-pin to bottom.

        Kept as a hook for callsites that historically forced scroll; user
        scroll-up auto-releases the anchor and Textual's compositor re-engages
        it when the user scrolls back to the end."""

    def _snap_to_bottom(self) -> None:
        """Re-engage the bottom anchor — used on explicit user actions
        (submitting a message, running a command) so the user immediately
        sees the result even if they had scrolled up."""
        try:
            chat_log = self._get_active_chat_log()
        except NoMatches:
            return
        chat_log.anchor()

    # ── Slash commands ────────────────────────────────────────────────

    async def _handle_command(self, cmd: str) -> None:
        chat_log = self._get_active_chat_log()
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        msg_arg = parts[1].strip() if len(parts) > 1 else ""

        if command in ("/quit", "/q"):
            if command == "/q" and self._session and self._session.extensions_mode:
                result = await self._commands.execute("/ext-mode")
                style = "yellow" if self._session.extensions_mode else "dim"
                await chat_log.mount(
                    Static(f"[{style}]{result.output}[/{style}]", markup=True)
                )
                self._wire_callbacks()
                self._update_status()
                return
            await self.action_quit_app()
            return

        if command == "/exit":
            if self._session and self._session.self_edit_mode:
                await self._session.toggle_self_edit_mode()
                await self._render_replay()
                await chat_log.mount(
                    Static("[dim]Returned to main session.[/dim]", markup=True)
                )
                self._wire_callbacks()
                self._update_status()
                self._smart_scroll()
            else:
                await self.action_quit_app()
            return

        if command in ("/i", "/self-edit"):
            subcommand = msg_arg.strip()
            if subcommand.lower().startswith("list"):
                # `/self-edit list [category]` — text-mode listing into the
                # chat log. Friendly fallback for tiny terminals and for
                # users who want the inventory grep-able in a transcript.
                parts = subcommand.split(None, 1)
                category = parts[1].strip() if len(parts) > 1 else None
                await self._show_self_edit_list_text(category)
                return
            await self.action_enter_self_edit()
            return

        if command in ("/clear", "/new"):
            if self._session and self._session.self_edit_mode:
                await chat_log.remove_children()
                await chat_log.mount(
                    Static(
                        "[dim]Self-edit session cleared. "
                        "Type /i <message> to continue or /exit to return.[/dim]",
                        markup=True,
                    )
                )
                return
            if command == "/clear":
                await chat_log.remove_children()
                return

        prior_agent_id = ""
        if command == "/new" and self._session is not None:
            prior_agent_id = str(
                getattr(self._session._loop, "agent_id", "") or ""
            )
            # In-place reset: keep the provider, tools, extensions and store
            # connection alive and just rotate the session id + loop. Much
            # faster than rebuilding a parallel session via action_new_chat,
            # and matches what users expect from `/new` (the current chat
            # disappears; a fresh one is ready immediately).
            await self._reset_current_session()
            if prior_agent_id:
                self._reapply_agent_profile(prior_agent_id)
            self._wire_callbacks()
            self._update_status()
            # Optional initial message: /new <message> starts the new
            # session and immediately sends <message> as the first user turn.
            if msg_arg:
                await self._submit_generated_prompt(msg_arg)
            return

        result = await self._commands.execute(cmd)
        action = result.metadata.get("action") if result.metadata else None
        if action == "send_prompt":
            prompt = str(result.metadata.get("prompt") or result.output)
            tool_names = result.metadata.get("tool_names")
            if not isinstance(tool_names, list):
                tool_names = None
            await self._submit_generated_prompt(prompt, tool_names=tool_names)
            return

        if action == "session_picker":
            sessions = result.metadata.get("sessions", [])
            if sessions:
                self._show_session_picker(sessions)
            return

        if action == "open_model_picker":
            self._open_model_picker_inline()
            return
        if action == "open_agent_picker":
            self._open_agent_picker_inline()
            return
        if action == "open_skill_picker":
            self._refill_input(self._config.prefixes.get("skills", "!"))
            return
        if action == "open_prompt_picker":
            self._refill_input(self._config.prefixes.get("prompts", "#"))
            return
        if action == "open_context_tree":
            self._open_context_tree()
            return
        if action == "open_theme_picker":
            self._open_theme_picker()
            return
        if action == "open_variant_picker":
            self._open_variant_picker()
            return
        if action == "theme_changed":
            theme = str(result.metadata.get("theme") or "")
            if theme:
                self._apply_theme(theme)
            return
        if action == "open_diff_view":
            title = str(result.metadata.get("title") or "Git Diff")
            diff = str(result.metadata.get("diff") or "")
            files = result.metadata.get("files")
            self.push_screen(
                GitDiffScreen(
                    title,
                    files if isinstance(files, list) else [],
                    diff,
                )
            )
            return

        if action == "copy_to_clipboard":
            content = result.metadata.get("clipboard_content", result.output)
            self.copy_to_clipboard(content)
            self.notify(result.output, timeout=2.0)
            return

        if action == "toast":
            self.notify(result.output, timeout=2.0)
            return

        if action not in ("model_changed", "new_session"):
            style = "yellow" if (result.error or (
                self._session and self._session.extensions_mode
            )) else "dim"
            await chat_log.mount(
                Static(f"[{style}]{result.output}[/{style}]", markup=True)
            )

        if action == "compact_requested":
            await self._handle_compact(chat_log)
            return

        if action == "debug_questions":
            self.run_worker(
                self._approval_ctrl.debug_questions(chat_log),
                name="debug_questions",
                group="debug",
                exclusive=True,
            )
        if action == "extensions_on":
            await chat_log.mount(
                Static("[dim]/q to quit extensions[/dim]", markup=True)
            )
        if action == "new_session" and prior_agent_id:
            self._reapply_agent_profile(prior_agent_id)
        if action in (
            "extensions_on",
            "extensions_off",
            "agent_activated",
            "model_changed",
            "variant_changed",
            "new_session",
            "session_resumed",
        ):
            self._wire_callbacks()
            self._update_status()
        if action == "session_resumed":
            await self._render_replay()

    async def _handle_compact(self, chat_log: VerticalScroll) -> None:
        """Run compaction and report before/after token counts."""
        if not self._session:
            await chat_log.mount(
                Static("[dim]No active session.[/dim]", markup=True)
            )
            return

        from taui.agent.context import estimate_total_tokens, manual_compact

        loop = self._session._loop
        before_tokens = estimate_total_tokens(loop._messages)
        removed = manual_compact(loop._messages)
        after_tokens = estimate_total_tokens(loop._messages)

        if removed:
            msg = (
                f"Compacted: removed {removed} messages. "
                f"Tokens: {before_tokens:,} → {after_tokens:,} "
                f"(saved {before_tokens - after_tokens:,})"
            )
        else:
            msg = f"No compaction needed. Current tokens: {before_tokens:,}"
        await chat_log.mount(Static(f"[dim]{msg}[/dim]", markup=True))
        chat_log.scroll_end()

    def _show_session_picker(self, sessions: list[dict]) -> None:
        """Open the sidebar on the sessions tab pre-populated with `sessions`."""
        try:
            sidebar = self.query_one(Sidebar)
        except NoMatches:
            return
        sidebar.set_sessions(
            sessions, self._session.session_id if self._session else ""
        )
        if not sidebar.has_class("visible"):
            sidebar.toggle()
        sidebar.action_show_tab("sessions")

    async def _open_session_picker(self, sessions: list[dict]) -> None:
        """Open the sessions sidebar (legacy entry point)."""
        self._show_session_picker(sessions)

    async def _resume_session(self, session_id: str) -> bool:
        """Resume a session into a new tab (or switch to it if already open)."""
        # If this session is already open as a tab, just switch to it
        if session_id in self._sessions:
            self._switch_to_session(session_id)
            return True

        if self._session is None:
            return False
        ok = await self._session.resume_session(session_id)
        if ok:
            # The active session has been mutated to point at the resumed session.
            # Update the SessionState's session_id to match.
            state = self._sessions.active
            if state is not None:
                old_id = state.session_id
                state.session_id = session_id
                # Re-register under the new ID
                self._sessions._states.pop(old_id, None)
                if old_id in self._sessions._order:
                    idx = self._sessions._order.index(old_id)
                    self._sessions._order[idx] = session_id
                self._sessions._states[session_id] = state
                self._sessions.active_id = session_id
            self._edited_files.clear()
            self._apply_default_agent_profile_id()
            self._wire_callbacks()
            self._update_status()
            await self._render_replay()
            self._refresh_tab_bar()
            return True

        error = (
            getattr(self._session, "last_resume_error", "")
            or f"Failed to resume session: {session_id}"
        )
        chat_log = self._get_active_chat_log()
        await chat_log.mount(Static(f"[red]{escape(error)}[/red]", markup=True))
        self._smart_scroll()
        return False

    async def _render_replay(self) -> None:
        """Clear the chat log and render the resumed session transcript."""
        if self._session is None:
            return
        chat_log = self._get_active_chat_log()
        await chat_log.remove_children()

        st = self._sessions.active
        if st is not None:
            st.turns = []
            st.current_turn = None
            st.reply_footer = None

        # Show context banner at the top of replayed sessions
        self._context_banner_shown = False
        await self._maybe_show_context_banner(chat_log)

        tool_section: Vertical | None = None
        pending_widgets: dict[str, ToolStatusWidget] = {}
        pending_order: list[str] = []
        turn_has_content = False
        turn_footer_agent_id = ""
        turn_footer_model = ""
        turn_input_tokens = 0
        turn_output_tokens = 0
        turn_tool_count = 0
        turn_user_text = ""
        turn_assistant_text = ""

        async def _flush_turn_footer() -> None:
            """Cap the just-replayed turn with a footer + per-turn summary."""
            nonlocal turn_footer_agent_id, turn_footer_model
            nonlocal turn_input_tokens, turn_output_tokens, turn_tool_count
            nonlocal turn_user_text, turn_assistant_text
            agent_id = turn_footer_agent_id
            model = turn_footer_model
            footer = ReplyFooter(agent_id, model, live=False)
            if st is not None and st.current_turn is not None:
                await st.current_turn.body.mount(footer)
                total = turn_input_tokens + turn_output_tokens
                if total == 0:
                    total = _estimate_tokens_from_text(
                        turn_user_text, turn_assistant_text
                    )
                st.current_turn.set_summary(
                    total_tokens=total,
                    tool_count=turn_tool_count,
                    model=model,
                    agent_id=agent_id,
                )
            else:
                await chat_log.mount(footer)
            turn_footer_agent_id = ""
            turn_footer_model = ""
            turn_input_tokens = 0
            turn_output_tokens = 0
            turn_tool_count = 0
            turn_user_text = ""
            turn_assistant_text = ""

        def _remember_turn_footer(item) -> None:
            nonlocal turn_footer_agent_id, turn_footer_model
            if not turn_footer_agent_id:
                turn_footer_agent_id = str(getattr(item, "agent_id", "") or "")
            if not turn_footer_model:
                turn_footer_model = str(getattr(item, "model", "") or "")

        for item in self._session.replay_items:
            if item.kind == "user":
                if turn_has_content:
                    await _flush_turn_footer()
                    turn_has_content = False
                tool_section = None
                await self._begin_turn(item.text, "", chat_log=chat_log, state=st)
                turn_user_text = item.text
            elif item.kind == "assistant":
                tool_section = None
                resp = AgentResponse()
                await self._mount_in_reply(resp, state=st)
                await resp.append_text(item.text)
                await resp.finalize()
                turn_has_content = True
                turn_assistant_text += item.text
                _remember_turn_footer(item)
            elif item.kind == "tool_call":
                if tool_section is None:
                    tool_section = Vertical(classes="tool-section")
                    await self._mount_in_reply(tool_section, state=st)
                args_str = ", ".join(
                    f"{key}={_trunc(str(value))}"
                    for key, value in (item.arguments or {}).items()
                )
                widget = ToolStatusWidget(item.name, args_str)
                await tool_section.mount(widget)
                key = item.call_id or f"__pos_{len(pending_order)}"
                pending_widgets[key] = widget
                pending_order.append(key)
                turn_has_content = True
                turn_tool_count += 1
                _remember_turn_footer(item)
            elif item.kind == "tool_result":
                key = item.call_id if item.call_id in pending_widgets else (
                    pending_order[0] if pending_order else ""
                )
                widget = pending_widgets.pop(key, None) if key else None
                if widget and key in pending_order:
                    pending_order.remove(key)
                if widget is not None:
                    if item.is_error:
                        await widget.fail(item.text)
                    else:
                        await widget.complete(item.text)
            elif item.kind == "usage":
                turn_input_tokens += item.input_tokens
                turn_output_tokens += item.output_tokens
            elif item.kind == "error":
                tool_section = None
                err = Static(
                    f"[red]Error: {escape(item.text)}[/red]",
                    markup=True,
                )
                await self._mount_in_reply(err, state=st)
                turn_has_content = True
                _remember_turn_footer(item)

        if turn_has_content:
            await _flush_turn_footer()
        if st is not None:
            self._autocollapse_old_turns(st)
        # AgentResponse (Markdown) widgets render asynchronously, so the
        # chat-log's virtual size keeps growing for several refresh cycles
        # after the last mount returns. Poll scroll_end on a short worker
        # until the scroll position settles, so the user lands at the end
        # of the transcript rather than mid-history.
        self._pin_replay_to_end()

    @work(exclusive=True, group="replay_scroll")
    async def _pin_replay_to_end(self) -> None:
        try:
            chat_log = self._get_active_chat_log()
        except NoMatches:
            return
        # Re-engage anchor so any subsequent content growth also sticks.
        chat_log.anchor()
        last_y = -1.0
        stable_passes = 0
        for _ in range(40):  # up to ~2s
            await asyncio.sleep(0.05)
            try:
                chat_log.scroll_end(animate=False, immediate=True, force=True)
            except Exception:
                return
            y = float(chat_log.scroll_y)
            if y == last_y:
                stable_passes += 1
                if stable_passes >= 3:
                    break
            else:
                stable_passes = 0
                last_y = y

    # ── Actions ───────────────────────────────────────────────────────

    async def action_quit_app(self) -> None:
        # Reset terminal title
        self._set_terminal_title("")
        # Close all sessions
        for sid in list(self._sessions.order):
            state = self._sessions.get(sid)
            if state is not None:
                try:
                    await state.session.close()
                except Exception:
                    pass
        self.exit()

    async def _reset_current_session(self) -> None:
        """Fast in-place reset of the active session.

        Reuses the existing provider, tool registry, executor, extensions,
        store, and stream — only the agent loop and session id are rotated.
        Visually clears the chat log so the new session starts fresh.
        """
        if self._session is None:
            return
        await self._session.new_session()
        try:
            chat_log = self._get_active_chat_log()
            await chat_log.remove_children()
            await self._mount_splash(chat_log)
        except Exception:
            pass
        st = self._sessions.active
        if st is not None:
            st.turns = []
            st.current_turn = None
            st.reply_footer = None
            st.session_id = self._session.session_id
            st.queued.clear()
        self._context_banner_shown = False
        self._pending_files.clear()
        self._pending_folders.clear()

    async def action_new_chat(self) -> None:
        """Create a new parallel session tab (does NOT cancel existing sessions)."""
        prior_agent_id = ""
        if self._session:
            prior_agent_id = str(
                getattr(self._session._loop, "agent_id", "") or ""
            )

        # Create a brand-new session. Do NOT call new_session() on the old
        # session — that would reset the old session's loop/messages.
        new_session = await Session.create(self._config)
        await self._add_session(new_session)

        if prior_agent_id:
            self._reapply_agent_profile(prior_agent_id)
        else:
            self._apply_default_agent_profile()
        self._wire_callbacks()
        self._update_status()

    async def action_cancel_request(self) -> None:
        state = self._sessions.active
        if state is not None and state.approval_ctrl.has_active_panel():
            state.approval_ctrl.cancel_active_panel()
        if state is not None:
            state.approval_ctrl.cancel_active_approval()
        if state is not None and state.is_processing:
            # Clear queues for the active session only
            state.queued.clear()
            if state.session:
                state.session._loop._steering_queue.clear()
            # Cancel only this session's workers
            sid = state.session_id
            for worker in list(self.workers):
                if worker.group == f"send-{sid}":
                    worker.cancel()
            # Halt any in-flight tool widgets (sub-agent spinners, etc.)
            if state.tool_ctrl is not None:
                await state.tool_ctrl.cancel_active("Cancelled")
        # Double-press quit check
        now = time.monotonic()
        if now - self._last_ctrl_c_time < 0.5:
            await self.action_quit_app()
            return
        self._last_ctrl_c_time = now

    async def action_ctrl_d(self) -> None:
        now = time.monotonic()
        if now - self._last_ctrl_d_time < 0.5:
            await self.action_quit_app()
            return
        self._last_ctrl_d_time = now

    async def action_close_tab(self) -> None:
        """Close the current session tab (Ctrl+W)."""
        if len(self._sessions) <= 1:
            # Last tab — don't close, just clear
            return
        state = self._sessions.active
        if state is None:
            return
        # Cancel any in-flight work for this session
        sid = state.session_id
        for worker in list(self.workers):
            if worker.group == f"send-{sid}":
                worker.cancel()
        # Close the session
        try:
            await state.session.close()
        except Exception:
            pass
        # Remove the chat log widget
        if state.chat_log is not None:
            await state.chat_log.remove()
        # Remove from manager (switches active to next tab)
        self._sessions.remove(sid)
        # Show the new active session's chat log
        new_state = self._sessions.active
        if new_state is not None and new_state.chat_log is not None:
            new_state.chat_log.remove_class("hidden-chat-log")
        self._wire_callbacks()
        self._update_status()
        self._refresh_tab_bar()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one(Sidebar)
        sidebar.toggle()
        if sidebar.has_class("visible"):
            self.run_worker(
                self._refresh_sidebar_sessions(),
                name="refresh_sidebar_sessions",
                exclusive=True,
            )

    def action_toggle_info_sidebar(self) -> None:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        info_sidebar = self.query_one(SessionInfoSidebar)
        info_sidebar.toggle()
        if info_sidebar.has_class("visible"):
            self._refresh_info_sidebar()
            info_sidebar.focus()

    # ── Cross-pane focus navigation ──────────────────────────────────
    # Three focus zones, left → right: [Sidebar] [ChatInput] [InfoSidebar].
    # alt+left / alt+right cycle focus across the visible zones so the TUI
    # is fully keyboard-navigable. Hidden sidebars are skipped.

    def _focus_zones(self) -> list[str]:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        zones: list[str] = []
        try:
            if self.query_one(Sidebar).has_class("visible"):
                zones.append("sidebar")
        except NoMatches:
            pass
        zones.append("chat-input")
        try:
            if self.query_one(SessionInfoSidebar).has_class("visible"):
                zones.append("info-sidebar")
        except NoMatches:
            pass
        return zones

    def _current_focus_zone(self) -> str:
        """Return the zone currently containing focus, or 'chat-input' as default."""
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        focused = self.focused
        if focused is None:
            return "chat-input"
        node = focused
        while node is not None:
            if isinstance(node, Sidebar):
                return "sidebar"
            if isinstance(node, SessionInfoSidebar):
                return "info-sidebar"
            node = node.parent
        return "chat-input"

    def _focus_zone(self, zone: str) -> None:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        if zone == "sidebar":
            try:
                sidebar = self.query_one(Sidebar)
                sidebar._focus_active()
            except NoMatches:
                pass
        elif zone == "info-sidebar":
            try:
                self.query_one(SessionInfoSidebar).focus()
            except NoMatches:
                pass
        else:
            try:
                self.query_one("#chat-input", ChatInput).focus()
            except NoMatches:
                pass

    def action_focus_pane_left(self) -> None:
        zones = self._focus_zones()
        cur = self._current_focus_zone()
        if cur not in zones:
            cur = "chat-input"
        idx = zones.index(cur)
        if idx > 0:
            self._focus_zone(zones[idx - 1])

    def action_focus_pane_right(self) -> None:
        zones = self._focus_zones()
        cur = self._current_focus_zone()
        if cur not in zones:
            cur = "chat-input"
        idx = zones.index(cur)
        if idx < len(zones) - 1:
            self._focus_zone(zones[idx + 1])

    async def action_next_tab(self) -> None:
        order = list(self._sessions.order)
        if len(order) < 2:
            return
        cur = self._sessions.active_id
        if cur not in order:
            return
        nxt = order[(order.index(cur) + 1) % len(order)]
        self._switch_to_session(nxt)

    async def action_prev_tab(self) -> None:
        order = list(self._sessions.order)
        if len(order) < 2:
            return
        cur = self._sessions.active_id
        if cur not in order:
            return
        prv = order[(order.index(cur) - 1) % len(order)]
        self._switch_to_session(prv)

    def on_descendant_focus(self, event) -> None:
        """Track which pane has focus and dim the chat panel when focus is in a sidebar.

        Visual cue: when the user moves focus into the left or right sidebar
        (via alt+left / alt+right / ctrl+b / ctrl+r), the chat input + info
        bar render in muted gray so it's obvious that typing won't land there.
        """
        zone = self._current_focus_zone()
        try:
            container = self.query_one("#chat-container")
        except NoMatches:
            return
        if zone == "chat-input":
            container.remove_class("chat-unfocused")
        else:
            container.add_class("chat-unfocused")

    async def _refresh_sidebar_sessions(self) -> None:
        if self._session is None:
            return
        try:
            sessions = await self._session.list_sessions()
        except Exception:
            sessions = []
        try:
            sidebar = self.query_one(Sidebar)
        except NoMatches:
            return
        sidebar.set_sessions(sessions, self._session.session_id or "")

    def _refresh_info_sidebar(self) -> None:
        from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

        try:
            info_sidebar = self.query_one(SessionInfoSidebar)
        except NoMatches:
            return
        if self._session is None:
            info_sidebar.update_info()
            return
        loop = self._session._loop
        agent_id = str(getattr(loop, "agent_id", "") or "")
        agent_name = ""
        agent_prompt = ""
        try:
            profile = SelfEditStore(self._config.working_dir).load_agents().get(
                agent_id.upper()
            )
            if profile is not None:
                agent_name = profile.name
                agent_prompt = profile.prompt or ""
        except Exception:
            pass
        session_name = ""
        description = getattr(self._session, "description", None)
        if description:
            session_name = str(description)
        edited_files = [
            {
                "path": path,
                "display": _relpath_or_basename(path, self._config.working_dir),
                "added": data["added"],
                "removed": data["removed"],
            }
            for path, data in sorted(self._edited_files.items())
        ]
        mcp_servers: list[tuple[str, bool]] = []
        mcp_manager = getattr(self._session, "_mcp_manager", None)
        if mcp_manager is not None:
            connected = set(getattr(mcp_manager, "connected_servers", []) or [])
            for name in getattr(mcp_manager, "server_names", []) or []:
                mcp_servers.append((name, name in connected))
        tools: list[str] = []
        registry = getattr(self._session, "_registry", None)
        if registry is not None:
            tools = list(getattr(registry, "names", []) or [])
        info_sidebar.update_info(
            session_id=self._session.session_id or "",
            session_name=session_name,
            agent_id=agent_id,
            agent_id_color=_agent_color(agent_id) if agent_id else "",
            agent_name=agent_name,
            agent_prompt_preview=agent_prompt,
            edited_files=edited_files,
            lsp_status="not connected",
            mcp_servers=mcp_servers,
            tools=tools,
        )

    def _record_edit(self, name: str, arguments: dict) -> None:
        """Track edit/write calls so the info sidebar can show +/- line counts."""
        path: str = ""
        added = 0
        removed = 0
        if name == "edit":
            path = str(arguments.get("file_path", ""))
            old_s = str(arguments.get("old_string", "") or "")
            new_s = str(arguments.get("new_string", "") or "")
            removed = old_s.count("\n") + (1 if old_s else 0)
            added = new_s.count("\n") + (1 if new_s else 0)
        elif name == "write":
            path = str(arguments.get("file_path", ""))
            content = str(arguments.get("content", "") or "")
            added = content.count("\n") + (1 if content else 0)
        else:
            return
        if not path:
            return
        entry = self._edited_files.setdefault(path, {"added": 0, "removed": 0})
        entry["added"] += added
        entry["removed"] += removed

    async def action_show_context(self) -> None:
        if not self._session:
            return
        messages = self._session._loop._messages
        self.push_screen(ContextBreakdownScreen(messages))

    async def action_enter_self_edit(self) -> None:
        """Ctrl+E: open the self-edit modal (futuristic yellow console)."""
        from taui.self_edit.factory import _safe_active_scope
        from taui.tui.screens.self_edit_modal import SelfEditModal

        scope = _safe_active_scope(self._config.working_dir)

        def _on_modal_close(_result: str | None) -> None:
            # Refresh the agent color cache so any changes made in the
            # modal are reflected immediately in the info bar, reply
            # footers, and progress indicators.
            sync_agent_colors(self._config.working_dir)
            self._update_status()

        self.push_screen(
            SelfEditModal(self._config.working_dir, initial_scope=scope),
            _on_modal_close,
        )

    async def _show_self_edit_list_text(self, category: str | None) -> None:
        """Render the self-edit inventory as plain text into the chat log."""
        from taui.self_edit.list_view import format_inventory_listing

        chat_log = self._get_active_chat_log()
        try:
            text = format_inventory_listing(
                self._config.working_dir, category=category
            )
        except KeyError:
            text = (
                f"[bold #ffae00]Unknown category:[/bold #ffae00] {escape(category or '')}\n"
                "Valid categories: agents, skills, commands, tools, prompts, mcp."
            )
        await chat_log.mount(Static(text, markup=True))
        self._smart_scroll()

    def _self_edit_scope_path(self, scope: str) -> Path:
        if scope == "project":
            return self._config.working_dir / ".taui"
        return Path.home() / ".taui"

    def _self_edit_scope_line(self, scope: str) -> str:
        path = self._self_edit_scope_path(scope)
        return f"[#f0c808]Current scope: {escape(scope)} {escape(str(path))}[/#f0c808]"

    def _apply_self_edit_profile(self, profile: AgentProfile) -> None:
        if self._session is None:
            return
        from taui.agent.loop import AgentLoop
        from taui.agent.types import Message
        from taui.tools.executor import PolicyDecision, ToolExecutor

        registry = self._session._registry
        if profile.allowed_tools:
            available = [name for name in profile.allowed_tools if name in registry.names]
            registry = registry.subset(available) if available else registry
        executor = ToolExecutor(registry=registry, policy=self._session._executor._policy)

        # Apply per-tool policies from tool_config
        for tool_name, tc in profile.tool_config.items():
            try:
                decision = PolicyDecision(tc.policy)
            except ValueError:
                continue
            executor._policy.set(tool_name, decision)

        # Auto-approve all tools when the profile requests it
        if profile.auto_approve_all:
            for tool_name in registry.names:
                executor._policy.set(tool_name, PolicyDecision.AUTO)
        if profile.provider:
            self._config.provider = profile.provider
        if profile.model:
            self._config.model = profile.model
        self._config.system_prompt = profile.prompt
        self._session.config = self._config
        self._session._system_prompt = profile.prompt
        self._session._base_system_prompt = profile.prompt

        old_loop = self._session._loop
        stream_id = old_loop.stream_id
        messages = old_loop._messages
        loop = AgentLoop(
            agent_id=profile.id,
            llm=self._session._provider,
            executor=executor,
            stream=self._session._stream,
            system_prompt=profile.prompt,
            model=self._config.model,
            model_variant=self._config.model_variant,
            max_turns=self._config.max_turns,
            provider_name=self._config.provider,
        )
        loop.stream_id = stream_id
        # Preserve conversation context: carry over messages, updating the
        # system prompt to the new profile's prompt.
        if messages:
            messages[0] = Message(role="system", content=profile.prompt)
            loop._messages = messages
        self._session._replace_loop(loop)
        self._wire_callbacks()
        self._update_status()
        # Refresh context-start banner immediately (synchronous) and also
        # notify listeners so any other consumers react.
        self._refresh_context_banner()
        self._session._notify_config_changed()

    def on_key(self, event: Key) -> None:
        """Intercept keys when Info2 is in model/agent mode."""
        from taui.tui.widgets.info2 import Info2Mode

        info2 = self.query_one("#info2", Info2)
        if not info2.is_active:
            return
        if info2.mode == Info2Mode.COMPLETIONS:
            return  # ChatInput handles completion keys
        if info2.mode == Info2Mode.QUESTIONS:
            return  # Embedded QuestionsPanel handles its own keys
        if info2.mode == Info2Mode.CONTEXT:
            if event.key not in ("up", "down", "enter", "space", "escape"):
                return
            event.prevent_default()
            event.stop()
            if event.key == "escape":
                info2.hide()
                return
            try:
                tree = info2.query_one("#context-tree", Tree)
            except NoMatches:
                return
            if event.key == "up":
                tree.action_cursor_up()
            elif event.key == "down":
                tree.action_cursor_down()
            else:
                tree.action_toggle_node()
            return

        if event.key == "up":
            event.prevent_default()
            event.stop()
            info2.move_up()
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            info2.move_down()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            info2.accept()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            from taui.tui.widgets.info2 import Info2Mode
            if info2.mode == Info2Mode.APPROVAL:
                info2.dismiss()
            else:
                info2.hide()

    async def action_escape(self) -> None:
        info2 = self.query_one("#info2", Info2)
        if info2.is_active:
            from taui.tui.widgets.info2 import Info2Mode
            if info2.mode == Info2Mode.APPROVAL:
                info2.dismiss()
            else:
                info2.hide()
            return

    @on(Sidebar.Dismiss)
    def handle_sidebar_dismiss(self, event: Sidebar.Dismiss) -> None:
        self.query_one("#chat-input", ChatInput).focus()

    @on(Sidebar.SessionSelected)
    def handle_sidebar_session_selected(
        self, event: Sidebar.SessionSelected
    ) -> None:
        if not event.session_id or self._session is None:
            return
        if event.session_id == self._session.session_id:
            return
        # Check if this session is already open as a tab
        if event.session_id in self._sessions:
            self._switch_to_session(event.session_id)
        else:
            self.run_worker(
                self._resume_session(event.session_id),
                name="session_resume",
                exclusive=True,
            )

    def _switch_to_session(self, session_id: str) -> None:
        """Switch the visible session to `session_id` without cancelling anything."""
        state = self._sessions.get(session_id)
        if state is None:
            return

        # Hide current chat log
        old_state = self._sessions.active
        if old_state is not None and old_state.chat_log is not None:
            old_state.chat_log.add_class("hidden-chat-log")

        # Show new chat log
        self._sessions.active_id = session_id
        if state.chat_log is not None:
            state.chat_log.remove_class("hidden-chat-log")

        self._wire_callbacks()
        self._update_status()
        self._refresh_tab_bar()
        self.query_one("#chat-input", ChatInput).focus()


def _relpath_or_basename(path: str, root: Path) -> str:
    """Return *path* relative to *root* when possible, else its basename."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return Path(path).name or path


_FOLDER_LISTING_MAX_ENTRIES = 200
_FOLDER_LISTING_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
    }
)


def _render_folder_listing(root: Path) -> str:
    """Render a tree-style listing of *root* (capped, with cruft filtered).

    Used when a folder is attached via the sidebar: we want the model to see
    the folder structure without dragging in every binary, lockfile, or
    `.git` blob. Hidden directories and common build/cache dirs are pruned.
    """

    if not root.is_dir():
        return ""

    lines: list[str] = [f"{root.name}/"]
    count = [0]  # mutable so the recursive helper can bump it

    def _walk(directory: Path, prefix: str) -> None:
        try:
            entries = sorted(
                directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except (OSError, PermissionError):
            return
        # Pre-filter so the connector glyph matches the real "last" entry.
        visible = [
            entry
            for entry in entries
            if not entry.name.startswith(".")
            and entry.name not in _FOLDER_LISTING_SKIP_DIRS
        ]
        for index, entry in enumerate(visible):
            if count[0] >= _FOLDER_LISTING_MAX_ENTRIES:
                lines.append(f"{prefix}…")
                return
            is_last = index == len(visible) - 1
            connector = "└─ " if is_last else "├─ "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            count[0] += 1
            if entry.is_dir():
                extension = "   " if is_last else "│  "
                _walk(entry, prefix + extension)

    _walk(root, "")
    return "\n".join(lines)


def _estimate_tokens_from_text(*texts: str) -> int:
    """Rough 1-token-per-4-chars fallback for providers that don't report usage."""
    total_chars = sum(len(t or "") for t in texts)
    if total_chars == 0:
        return 0
    return max(1, total_chars // 4 + 1)


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


# Light gray = active (in the loop's effective registry); dark gray = available
# but inactive (filtered out by the current variant's tool selection).
_TOOL_ACTIVE_COLOR = "#bfbfbf"
_TOOL_INACTIVE_COLOR = "#5a5a5a"


def _render_tools_table(
    available: list[str], active: set[str], *, columns: int = 3,
) -> str:
    """Render tool names as a fixed-column table with active/inactive coloring."""
    if not available:
        return ""
    names = sorted(set(available))
    col_width = max((len(n) for n in names), default=0) + 2
    rows: list[str] = []
    for i in range(0, len(names), columns):
        chunk = names[i:i + columns]
        cells = []
        for j, name in enumerate(chunk):
            color = _TOOL_ACTIVE_COLOR if name in active else _TOOL_INACTIVE_COLOR
            padded = name if j == len(chunk) - 1 else name.ljust(col_width)
            cells.append(f"[{color}]{padded}[/{color}]")
        rows.append("".join(cells))
    return "\n".join(rows)


def _model_completion_matches(prefix: str, provider: str, model_id: str) -> bool:
    needle = prefix.casefold().strip()
    if not needle:
        return True
    provider = provider.casefold()
    model_id = model_id.casefold()
    value = f"{provider}/{model_id}"
    if value.startswith(needle) or model_id.startswith(needle):
        return True
    tokens = model_id.replace("_", "-").replace(".", "-").split("-")
    if any(token.startswith(needle) for token in tokens):
        return True
    return _is_ordered_subsequence(needle, model_id)


def _is_ordered_subsequence(needle: str, haystack: str) -> bool:
    index = 0
    for char in haystack:
        if index < len(needle) and needle[index] == char:
            index += 1
    return index == len(needle)


def _fuzzy_match(query: str, target: str) -> bool:
    """Substring or ordered-subsequence match."""
    return query in target or _is_ordered_subsequence(query, target)
