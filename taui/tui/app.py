"""Main Textual application for taui."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Key
from textual.widgets import Markdown, Static, Tree

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, estimate_total_tokens
from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.config import Config
from taui.self_edit.store import AgentProfile, SelfEditStore
from taui.session import Session
from taui.tui.approval_controller import ApprovalController
from taui.tui.messages import (
    CompactionOccurred,
    StreamReasoningDelta,
    StreamTextDelta,
    ToolEnded,
    ToolStarted,
)
from taui.tui.screens.context_breakdown import ContextBreakdownScreen
from taui.tui.tool_controller import ToolController
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.info_bar import InfoBar, _agent_color
from taui.tui.widgets.reply_footer import ReplyFooter
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.spinner import ActivityProgress
from taui.tui.widgets.tool_status import ToolStatusWidget

logger = logging.getLogger(__name__)


class TauiApp(App[None]):
    """Textual TUI for taui."""

    TITLE = "taui"

    CSS = """
    Screen {
        background: $surface-darken-1;
    }
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }
    #chat-area {
        width: 1fr;
        height: 1fr;
    }
    #chat-container {
        height: auto;
        border: tall $surface-darken-1;
        background: $surface;
        margin: 0 1;
        padding: 0;
    }
    #chat-log {
        height: 1fr;
        padding: 1 2;
        scrollbar-size: 0 0;
    }
    #activity-progress {
        dock: bottom;
    }
    .user-message {
        background: $surface;
        padding: 1 2;
        margin: 1 0 1 0;
    }
    .tool-section {
        height: auto;
        padding: 0;
        margin: 1 0;
    }
    .steer-indicator {
        color: $text-muted;
        padding: 0 2;
    }
    .queue-indicator {
        color: yellow;
        padding: 0 2;
    }
    .reasoning-text {
        color: $text-muted;
        padding: 0 2;
        margin: 0 0 1 0;
    }
    .turn-summary {
        padding: 0 2;
        margin: 0 0 1 0;
    }
    Markdown {
        padding: 0 2;
        margin: 0 0 1 0;
        color: white;
    }
    AgentResponse {
        margin: 0;
    }
    AgentResponse > MarkdownParagraph:last-child {
        margin-bottom: 0;
    }
    MarkdownBlock > .code_inline {
        background: #243244;
        color: #fbbf24;
    }
    MarkdownBlock > .strong {
        color: #f8fafc;
        text-style: bold;
    }
    MarkdownBlock > .em {
        color: #c4b5fd;
        text-style: italic;
    }
    MarkdownH1 {
        color: #7dd3fc;
        text-style: bold;
    }
    MarkdownH2 {
        color: #67e8f9;
        text-style: bold;
    }
    MarkdownH3 {
        color: #a7f3d0;
        text-style: bold;
    }
    MarkdownH4, MarkdownH5 {
        color: #e2e8f0;
        text-style: bold;
    }
    MarkdownH6 {
        color: #94a3b8;
        text-style: bold;
    }
    MarkdownBullet {
        color: #67e8f9;
    }
    MarkdownBlockQuote {
        background: #1f2937 45%;
        border-left: outer #5eead4;
        color: #cbd5e1;
    }
    MarkdownFence {
        background: #111827;
        color: #e5e7eb;
    }
    MarkdownTableContent {
        keyline: thin #334155;
    }
    MarkdownTableContent > .header {
        color: #7dd3fc;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+n", "new_chat", "New session"),
        ("ctrl+c", "cancel_request", "Cancel"),
        ("ctrl+d", "ctrl_d", ""),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+e", "enter_self_edit", "Self-edit"),
        ("ctrl+x", "show_context", "Context"),
        ("escape", "escape", ""),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._config = config or Config.load()
        self._session: Session | None = None
        self._session_initializing = False
        self._is_processing = False

        self._tool_ctrl = ToolController(self)
        self._approval_ctrl = ApprovalController(self)

        # Double-press quit tracking
        self._last_ctrl_c_time: float = 0.0
        self._last_ctrl_d_time: float = 0.0

        # Streaming / chat-turn state
        self._current_response: AgentResponse | None = None
        self._current_reasoning: Static | None = None
        self._reasoning_buf: str = ""
        self._streamed_text: bool = False
        self._reply_footer: ReplyFooter | None = None

        # Queue for follow-up messages
        self._queued: list[tuple[str, list[str] | None]] = []
        self._pending_indicators: list[tuple[str, str]] = []

        # History persistence
        self._history_file = Path.home() / ".cache" / "taui" / "prompt_history"
        self._history: list[str] = []

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
        with Horizontal(id="main-layout"):
            yield Sidebar(self._config.working_dir)
            with Vertical(id="chat-area"):
                with VerticalScroll(id="chat-log"):
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

    async def on_mount(self) -> None:
        self._commands = self._build_commands()
        self._configure_chat_input()
        self._session_initializing = True
        self.query_one(InfoBar).update_info(
            provider=self._config.provider,
            model=self._config.model,
            agent_id="" if self._config.session_id else "DEF",
        )
        self._set_chat_panel_visible(False)
        self.query_one(ActivityProgress).start_breathing()

        chat_log = self.query_one("#chat-log", VerticalScroll)
        chat_log.anchor()

        self.run_worker(
            self._initialize_session(),
            name="session_init",
            group="startup",
            exclusive=True,
            exit_on_error=False,
        )

    def _set_chat_panel_visible(self, visible: bool) -> None:
        """Show/hide the chat panel contents while keeping the bottom bar."""
        for selector in ("#chat-log", "#info2", "#chat-container"):
            try:
                self.query_one(selector).display = visible
            except Exception:
                pass

    async def _initialize_session(self) -> None:
        try:
            self._session = await Session.create(self._config)
        except Exception as exc:
            logger.exception("Failed to create session")
            self._session_initializing = False
            self.query_one(ActivityProgress).stop()
            self._set_chat_panel_visible(True)
            await self._show_startup_error(exc)
            return

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

    def _configure_chat_input(self) -> None:
        """Load input history and command completions."""
        # Load history
        self._load_history()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.load_history(self._history)
        chat_input.set_model_completer(self._complete_model_arg)
        chat_input.set_arg_completer("agents", self._complete_agents_arg)
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
        chat_log = self.query_one("#chat-log", VerticalScroll)
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
                # File stores oldest first; we want newest first
                self._history = list(reversed(lines[-500:]))
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
                f.write(text.replace("\n", "\\n") + "\n")
        except Exception:
            pass
        # Update ChatInput's history
        self.query_one("#chat-input", ChatInput).load_history(self._history)

    # ── @file expansion ───────────────────────────────────────────────

    def _expand_file_refs(self, text: str) -> tuple[str, list[str] | None]:
        """Expand @path references to file contents or image attachments.

        Returns (expanded_text, images) where images is a list of data: URLs
        for any referenced image files, or None if no images were found.
        """
        from taui.tui.widgets.chat_input import _IMAGE_EXTENSIONS, _encode_image_file

        words = text.split()
        result: list[str] = []
        images: list[str] = []
        for word in words:
            if word.startswith("@") and len(word) > 1:
                fpath = Path(word[1:])
                if not fpath.is_absolute():
                    fpath = self._config.working_dir / fpath
                if fpath.is_file():
                    # Check if it's an image file
                    if fpath.suffix.lower() in _IMAGE_EXTENSIONS:
                        data_url = _encode_image_file(fpath)
                        if data_url:
                            images.append(data_url)
                            result.append(f"[Image {len(images)}]")
                            continue
                    # Text file
                    try:
                        content = fpath.read_text()
                        result.append(f"\n```{fpath.name}\n{content}\n```\n")
                        continue
                    except (OSError, UnicodeDecodeError):
                        pass
            result.append(word)
        return " ".join(result), images or None

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
            if prefix and not agent.id.lower().startswith(prefix.lower()):
                continue
            matches.append((agent.id, agent.name, False))
        return matches

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
        """Tear down any in-flight agent turn so the next session starts clean.
        Silences the current loop's callbacks first, then cancels the worker
        and resets TUI streaming state — without this, a mid-turn /new can
        leak streaming text, tool widgets, and 'Request cancelled.' notices
        into the fresh chat log."""
        if self._session is None:
            return

        old_loop = self._session._loop
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

        if self._approval_ctrl.has_active_panel():
            self._approval_ctrl.cancel_active_panel()
        self._approval_ctrl.cancel_active_approval()

        if self._is_processing:
            self._queued.clear()
            old_loop._steering_queue.clear()
            self.workers.cancel_all()
            # wait_for_complete swallows CancelledError but re-raises
            # WorkerCancelled, which is exactly what our own cancel_all
            # produces. Drain individually so cancellation is the success path.
            for worker in list(self.workers):
                try:
                    await worker.wait()
                except Exception:
                    pass
            self._set_busy(False)

        self._current_response = None
        self._current_reasoning = None
        self._reasoning_buf = ""
        self._streamed_text = False
        self._reply_footer = None
        self._pending_indicators.clear()
        self._tool_ctrl.reset()

        try:
            self.query_one(ActivityProgress).stop()
        except NoMatches:
            pass

    def _cycle_agent_profile(self) -> None:
        """Activate the next available agent profile by ID."""
        if self._session is None:
            return
        agents = SelfEditStore(self._config.working_dir).load_agents()
        profiles = sorted(agents.values(), key=lambda item: item.id)
        if not profiles:
            return
        active_id = str(getattr(self._session._loop, "agent_id", "") or "").upper()
        active_index = next(
            (index for index, profile in enumerate(profiles) if profile.id == active_id),
            -1,
        )
        next_profile = profiles[(active_index + 1) % len(profiles)]
        self._apply_self_edit_profile(next_profile)
        self._update_status()

    # ── Info bar ──────────────────────────────────────────────────────

    def _update_status(self) -> None:
        if not self._session:
            return
        info_bar = self.query_one(InfoBar)
        tokens = estimate_total_tokens(self._session._loop._messages)
        tracker = self._session.cost_tracker
        info_bar.update_info(
            provider=self._session.provider_name,
            model=self._session.model_name,
            tokens=tokens,
            max_tokens=DEFAULT_MAX_INPUT_TOKENS,
            cost=tracker.total_cost_usd,
            extensions_mode=self._session.extensions_mode,
            agent_id=str(getattr(self._session._loop, "agent_id", "") or ""),
        )
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.self_edit_mode = self._session.self_edit_mode
        except Exception:
            pass
        self._refresh_command_completions()

    # ── Agent callbacks ───────────────────────────────────────────────

    def _wire_callbacks(self) -> None:
        assert self._session is not None
        loop = self._session._loop
        loop._on_tool_call = self._tool_ctrl.on_tool_call
        loop._on_tool_result = self._tool_ctrl.on_tool_result
        loop._on_text = self._on_text
        loop._on_text_delta = self._on_text_delta_sync
        loop._on_reasoning_delta = self._on_reasoning_delta_sync
        loop._on_approval = self._approval_ctrl.on_approval
        loop._on_questions_batch = self._approval_ctrl.on_questions_batch
        loop._on_compact = self._on_compact_sync

        # Wire sub-agent callbacks so child tool calls are visible in the TUI
        try:
            from taui.tools.builtins.sub_agent import SubAgentTool

            registry = getattr(self._session, "_registry", None)
            if registry is not None:
                sub_agent = registry.get("sub_agent")
                if isinstance(sub_agent, SubAgentTool):
                    sub_agent._on_tool_call = self._tool_ctrl.on_tool_call
                    sub_agent._on_tool_result = self._tool_ctrl.on_tool_result
        except (ValueError, ImportError):
            pass

    def _on_text_delta_sync(self, fragment: str) -> None:
        """Handle real-time streaming token from the LLM provider."""
        self._streamed_text = True
        self.post_message(StreamTextDelta(fragment))

    def _on_reasoning_delta_sync(self, fragment: str) -> None:
        """Handle real-time streaming reasoning token from the LLM provider."""
        self.post_message(StreamReasoningDelta(fragment))

    async def _on_text(self, text: str) -> None:
        """Handle full text after turn — only used if no streaming occurred."""
        if not self._streamed_text:
            self.post_message(StreamTextDelta(text))

    def _on_compact_sync(self, removed: int, before: int, after: int) -> None:
        """Handle auto-compaction notification from the agent loop."""
        self.post_message(CompactionOccurred(removed, before, after))

    # ── Tool event handlers ───────────────────────────────────────────

    @on(CompactionOccurred)
    async def handle_compaction(self, event: CompactionOccurred) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
        msg = (
            f"Context auto-compacted: {event.removed} messages removed, "
            f"tokens {event.before_tokens:,} → {event.after_tokens:,}"
        )
        await chat_log.mount(Static(f"[dim]{msg}[/dim]", markup=True))
        chat_log.scroll_end()

    @on(ToolStarted)
    async def handle_tool_started(self, event: ToolStarted) -> None:
        await self._tool_ctrl.handle_tool_started(event)

    @on(ToolEnded)
    async def handle_tool_ended(self, event: ToolEnded) -> None:
        await self._tool_ctrl.handle_tool_ended(event)

    @on(InfoBar.AgentBadgeClicked)
    def handle_agent_badge_clicked(
        self, event: InfoBar.AgentBadgeClicked | None = None
    ) -> None:
        if self._session is None:
            return
        agents = sorted(
            SelfEditStore(self._config.working_dir).load_agents().values(),
            key=lambda item: item.id,
        )
        if not agents:
            return
        active_id = str(getattr(self._session._loop, "agent_id", "") or "")
        info2 = self.query_one("#info2", Info2)
        info2.show_agents(agents, current=active_id)

    @on(InfoBar.ModelBadgeClicked)
    def handle_model_badge_clicked(self, event: InfoBar.ModelBadgeClicked) -> None:
        self._open_model_picker()

    @on(InfoBar.ContextBadgeClicked)
    def handle_context_badge_clicked(self, event: InfoBar.ContextBadgeClicked) -> None:
        self._open_context_tree()

    @on(InfoBar.SessionBadgeClicked)
    def handle_session_badge_clicked(
        self, event: InfoBar.SessionBadgeClicked
    ) -> None:
        if self._session is None:
            return
        self.run_worker(
            self._load_and_show_sessions(), name="load_sessions", exclusive=True
        )

    async def _load_and_show_sessions(self) -> None:
        if self._session is None:
            return
        sessions = await self._session.list_sessions()
        if sessions:
            self._show_session_picker(sessions)

    def _open_model_picker(self) -> None:
        if self._session is None:
            return
        from taui.llm_provider.models import list_models

        provider = self._session.config.provider
        models = list_models(provider)
        info2 = self.query_one("#info2", Info2)
        info2.show_models(models, current=self._session.model_name)

    def _open_context_tree(self) -> None:
        if self._session is None:
            return
        info2 = self.query_one("#info2", Info2)
        info2.show_context_tree(
            self._session._loop._messages,
            DEFAULT_MAX_INPUT_TOKENS,
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

    # ── Streaming text handlers ───────────────────────────────────────

    @on(StreamTextDelta)
    async def handle_stream_text(self, event: StreamTextDelta) -> None:
        """Handle incoming text deltas — stream into AgentResponse widget."""
        # Finalize reasoning block when regular text starts arriving
        if self._current_reasoning is not None:
            self._current_reasoning = None
        if self._current_response is None:
            self._current_response = AgentResponse()
            await self._mount_in_reply(self._current_response)
        await self._current_response.append_text(event.text)
        self._smart_scroll()

    @on(StreamReasoningDelta)
    async def handle_stream_reasoning(self, event: StreamReasoningDelta) -> None:
        """Handle incoming reasoning deltas — stream into a dimmed Static widget."""
        self._reasoning_buf += event.text
        display = self._reasoning_buf
        if len(display) > 300:
            display = display[:300] + "..."
        if self._current_reasoning is None:
            self._current_reasoning = Static(
                f"[dim italic]{escape(display)}[/dim italic]",
                classes="reasoning-text",
                markup=True,
            )
            await self._mount_in_reply(self._current_reasoning)
        else:
            self._current_reasoning.update(
                f"[dim italic]{escape(display)}[/dim italic]"
            )
        self._smart_scroll()

    # ── Input handling ────────────────────────────────────────────────

    @on(ChatInput.Submitted)
    async def handle_input(self, event: ChatInput.Submitted) -> None:
        text = event.value
        images = event.images or None

        if text.startswith("/"):
            await self._handle_command(text)
            return

        if self._session is None:
            chat_log = self.query_one("#chat-log", VerticalScroll)
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

        if self._is_processing:
            if event.queue:
                # Alt+Enter while busy → queue
                self._queued.append((text, images))
                self._pending_indicators.append(("q", text))
                await self._show_indicator("q", text)
            else:
                # Enter while busy → steer
                assert self._session is not None
                self._session._loop.steer(text)
                self._pending_indicators.append(("s", text))
                await self._show_indicator("s", text)
            return

        # Normal send
        chat_log = self.query_one("#chat-log", VerticalScroll)
        display_text = escape(text)
        if images:
            labels = " ".join(f"\\[Image {i + 1}]" for i in range(len(images)))
            image_note = f"  [dim]{labels}[/dim]"
        else:
            image_note = ""
        await chat_log.mount(
            Static(
                f"[bold #e6edf3]{display_text}[/bold #e6edf3]{image_note}",
                classes="user-message",
                markup=True,
            )
        )
        # Clear the attachments bar after submit
        self.query_one(AttachmentsBar).clear_all()
        # Submitting is an explicit intent to see the result — re-arm anchor.
        self._snap_to_bottom()
        self._send_and_drain(text, images)

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
        chat_log = self.query_one("#chat-log", VerticalScroll)
        await chat_log.mount(
            Static(self._self_edit_scope_line(new_scope), markup=True)
        )
        self._update_status()

    @on(ChatInput.ImageAttached)
    async def handle_image_attached(
        self,
        event: ChatInput.ImageAttached,
    ) -> None:
        """Add pills to the attachments bar for newly attached images."""
        chat_input = self.query_one(ChatInput)
        bar = self.query_one(AttachmentsBar)
        # Sync bar with pending images — add pills for new ones
        existing = bar.count
        for i in range(existing, chat_input.pending_image_count):
            idx = i + 1
            bar.add(f"Image {idx}", chat_input._pending_images[i])

    @on(AttachmentsBar.Cleared)
    async def handle_attachment_cleared(
        self,
        event: AttachmentsBar.Cleared,
    ) -> None:
        """Remove the corresponding pending image when a pill is dismissed."""
        chat_input = self.query_one(ChatInput)
        idx = event.index
        if 0 <= idx < len(chat_input._pending_images):
            chat_input._pending_images.pop(idx)

    @on(ChatInput.InputCleared)
    async def handle_input_cleared(self, event: ChatInput.InputCleared) -> None:
        """Clear attachments bar when user double-presses Escape."""
        self.query_one(AttachmentsBar).clear_all()

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


    # ── Send message and drain queue ──────────────────────────────────

    @work(exclusive=True)
    async def _send_and_drain(
        self, text: str, images: list[str] | None = None
    ) -> None:
        assert self._session is not None
        self._set_busy(True)

        try:
            await self._do_send(text, images=images)

            # Drain queued messages
            while self._queued:
                msg, queued_images = self._queued.pop(0)
                chat_log = self.query_one("#chat-log", VerticalScroll)
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
                await self._do_send(msg, images=queued_images)
        finally:
            self._set_busy(False)

    async def _do_send(
        self, text: str, *, images: list[str] | None = None
    ) -> None:
        """Send a single message and display the result."""
        assert self._session is not None

        progress = self.query_one(ActivityProgress)
        agent_id = str(getattr(self._session._loop, "agent_id", "") or "")
        progress.set_active_style(_agent_color(agent_id) if agent_id else "#3fb950")
        progress.start()

        self._tool_ctrl.reset_section()
        self._current_response = None
        self._current_reasoning = None
        self._reasoning_buf = ""
        self._streamed_text = False
        self._reply_footer = None
        await self._begin_reply_footer()

        try:
            result = await self._session.send(text, images=images)

            # Finalize any streaming response
            await self._finalize_response()

            # If no streaming happened (fallback), show response as markdown
            if result.text and not self._streamed_text:
                await self._mount_in_reply(Markdown(result.text))

            # Turn summary
            summary_parts: list[str] = []
            tracker = self._session.cost_tracker
            if tracker.total_cost_usd > 0:
                summary_parts.append(f"${tracker.total_cost_usd:.4f}")
            for fn in self._session.hooks._hooks.get("turn_summary", []):
                try:
                    extra = fn(result, self._session)
                    if extra:
                        summary_parts.append(str(extra))
                except Exception:
                    pass
            if summary_parts:
                summary = f"[dim]{' · '.join(summary_parts)}[/dim]"
                await self._mount_in_reply(
                    Static(summary, classes="turn-summary", markup=True)
                )

            self._update_status()
            self._smart_scroll()
        except asyncio.CancelledError:
            await self._mount_in_reply(
                Static("[dim]Request cancelled.[/dim]", markup=True)
            )
        except Exception as exc:
            await self._mount_in_reply(
                Static(f"[red]Error: {exc}[/red]", markup=True)
            )
        finally:
            progress.stop()
            self._tool_ctrl.reset_section()
            # Intentionally do NOT clear `self._reply_footer` here. Stream
            # deltas are dispatched off Textual's message queue and a few
            # can still be pending after `_session.send()` returns. Nulling
            # the ref now would cause those late deltas to fall into the
            # `footer is None` branch of `_mount_in_reply` and mount their
            # content past the footer. The next turn's `_do_send` nulls it
            # (and `_begin_reply_footer` rebuilds a fresh one) once we're
            # safely past any in-flight callbacks from the prior turn.

    async def _finalize_response(self) -> None:
        """Finalize the current streaming response if any."""
        if self._current_response:
            await self._current_response.finalize()
            self._current_response = None
            # Reset tool section so the next tool group starts below the new text.
            self._tool_ctrl.reset_section()
        # Reset reasoning state for the next turn
        if self._current_reasoning is not None:
            self._current_reasoning = None
            self._reasoning_buf = ""

    # ── Busy state management ─────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._is_processing = busy
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.agent_busy = busy
        if not busy:
            self._pending_indicators.clear()
            chat_input.focus()

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

    # ── Per-reply footer ──────────────────────────────────────────────

    async def _begin_reply_footer(self) -> None:
        """Eagerly mount the per-turn footer at the start of `_do_send`.

        Doing this once, before any callbacks can fire, guarantees a single
        ReplyFooter per turn — no race window where two streaming callbacks
        both think they need to create one."""
        if self._reply_footer is not None:
            return
        chat_log = self.query_one("#chat-log", VerticalScroll)
        agent_id = ""
        model = ""
        if self._session is not None:
            agent_id = str(getattr(self._session._loop, "agent_id", "") or "")
            model = self._session.model_name or ""
        footer = ReplyFooter(agent_id, model)
        self._reply_footer = footer
        await chat_log.mount(footer)

    async def _mount_in_reply(self, widget) -> None:
        """Mount a widget into the chat log above the current turn's footer."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        footer = self._reply_footer
        if footer is not None:
            await chat_log.mount(widget, before=footer)
        else:
            await chat_log.mount(widget)

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
            chat_log = self.query_one("#chat-log", VerticalScroll)
        except NoMatches:
            return
        chat_log.anchor()

    # ── Slash commands ────────────────────────────────────────────────

    async def _handle_command(self, cmd: str) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
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
            await self._enter_self_edit_with_message(msg_arg)
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
            await self._begin_new_session()
            await chat_log.remove_children()

        result = await self._commands.execute(cmd)
        action = result.metadata.get("action") if result.metadata else None
        if action == "session_picker":
            sessions = result.metadata.get("sessions", [])
            if sessions:
                self._show_session_picker(sessions)
            return

        if action == "open_model_picker":
            self._open_model_picker()
            return
        if action == "open_agent_picker":
            self.handle_agent_badge_clicked(None)
            return
        if action == "open_context_tree":
            self._open_context_tree()
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
        """Show the inline session picker in Info2."""
        info2 = self.query_one("#info2", Info2)
        info2.show_sessions(sessions)

    async def _open_session_picker(self, sessions: list[dict]) -> None:
        """Open the inline session picker (legacy entry point)."""
        self._show_session_picker(sessions)

    async def _resume_session(self, session_id: str) -> bool:
        """Resume a session, render its transcript, and report failures inline."""
        if self._session is None:
            return False
        ok = await self._session.resume_session(session_id)
        if ok:
            self._apply_default_agent_profile_id()
            self._wire_callbacks()
            self._update_status()
            await self._render_replay()
            return True

        error = (
            getattr(self._session, "last_resume_error", "")
            or f"Failed to resume session: {session_id}"
        )
        chat_log = self.query_one("#chat-log", VerticalScroll)
        await chat_log.mount(Static(f"[red]{escape(error)}[/red]", markup=True))
        self._smart_scroll()
        return False

    async def _render_replay(self) -> None:
        """Clear the chat log and render the resumed session transcript."""
        if self._session is None:
            return
        chat_log = self.query_one("#chat-log", VerticalScroll)
        await chat_log.remove_children()
        tool_section: Vertical | None = None
        pending_widgets: dict[str, ToolStatusWidget] = {}
        pending_order: list[str] = []
        turn_has_content = False

        async def _flush_turn_footer() -> None:
            """Cap the just-replayed turn with a footer like a live turn."""
            agent_id = ""
            model = ""
            if self._session is not None:
                agent_id = str(
                    getattr(self._session._loop, "agent_id", "") or ""
                )
                model = self._session.model_name or ""
            await chat_log.mount(ReplyFooter(agent_id, model))

        for item in self._session.replay_items:
            if item.kind == "user":
                if turn_has_content:
                    await _flush_turn_footer()
                    turn_has_content = False
                tool_section = None
                await chat_log.mount(
                    Static(
                        f"[bold #e6edf3]{escape(item.text)}[/bold #e6edf3]",
                        classes="user-message",
                        markup=True,
                    )
                )
            elif item.kind == "assistant":
                tool_section = None
                resp = AgentResponse()
                await chat_log.mount(resp)
                await resp.append_text(item.text)
                await resp.finalize()
                turn_has_content = True
            elif item.kind == "tool_call":
                if tool_section is None:
                    tool_section = Vertical(classes="tool-section")
                    await chat_log.mount(tool_section)
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
            elif item.kind == "error":
                tool_section = None
                await chat_log.mount(
                    Static(
                        f"[red]Error: {escape(item.text)}[/red]",
                        markup=True,
                    )
                )
                turn_has_content = True

        if turn_has_content:
            await _flush_turn_footer()
        # AgentResponse (Markdown) widgets render asynchronously, so the
        # chat-log's virtual size keeps growing for several refresh cycles
        # after the last mount returns. Poll scroll_end on a short worker
        # until the scroll position settles, so the user lands at the end
        # of the transcript rather than mid-history.
        self._pin_replay_to_end()

    @work(exclusive=True, group="replay_scroll")
    async def _pin_replay_to_end(self) -> None:
        try:
            chat_log = self.query_one("#chat-log", VerticalScroll)
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
        if self._session:
            await self._session.close()
        self.exit()

    async def action_new_chat(self) -> None:
        if self._session:
            prior_agent_id = str(
                getattr(self._session._loop, "agent_id", "") or ""
            )
            await self._begin_new_session()
            chat_log = self.query_one("#chat-log", VerticalScroll)
            await chat_log.remove_children()
            await self._session.new_session()
            if prior_agent_id:
                self._reapply_agent_profile(prior_agent_id)
            self._wire_callbacks()
            self._update_status()

    async def action_cancel_request(self) -> None:
        if self._approval_ctrl.has_active_panel():
            self._approval_ctrl.cancel_active_panel()
        self._approval_ctrl.cancel_active_approval()
        if self._is_processing:
            # Clear queues
            self._queued.clear()
            if self._session:
                self._session._loop._steering_queue.clear()
            # Cancel the worker
            self.workers.cancel_all()
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

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle()

    async def action_show_context(self) -> None:
        if not self._session:
            return
        messages = self._session._loop._messages
        self.push_screen(ContextBreakdownScreen(messages))

    async def action_enter_self_edit(self) -> None:
        """Ctrl+E: show usage hint — actual entry is via /i <msg>."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        await chat_log.mount(
            Static(
                "[dim]Use /i <message> to start a self-edit session.[/dim]",
                markup=True,
            )
        )
        self._smart_scroll()

    def _self_edit_scope_path(self, scope: str) -> Path:
        if scope == "project":
            return self._config.working_dir / ".taui"
        return Path.home() / ".taui"

    def _self_edit_scope_line(self, scope: str) -> str:
        path = self._self_edit_scope_path(scope)
        return f"[#f0c808]Current scope: {escape(scope)} {escape(str(path))}[/#f0c808]"

    def _self_edit_scope_banner(self) -> str:
        """Rich-markup block shown when self-edit mode opens — scope, paths, counts."""
        from taui.self_edit.factory import collect_self_edit_inventory

        inv = collect_self_edit_inventory(self._config.working_dir)

        global_path = str(self._self_edit_scope_path("global"))
        project_path = str(self._self_edit_scope_path("project"))

        header_row = (
            f"{'Category':<20}"
            f"{'built-in':<18}"
            f"{'global':<10}"
            f"{'project':<10}"
        )
        body_rows: list[str] = []
        for r in inv.rows:
            body_rows.append(
                f"{r.label:<20}"
                f"{r.builtin_label:<18}"
                f"{r.global_count:<10}"
                f"{r.project_count:<10}"
            )

        lines = [
            "[bold #f0c808]── self-edit mode · /exit to return ──[/bold #f0c808]",
            f"[bold]{header_row}[/bold]",
            *body_rows,
            "",
            f"[white]global   {escape(global_path)}[/white]",
            f"[white]project  {escape(project_path)}[/white]",
            "",
            "[#f0c808]Tab toggles scope[/#f0c808]",
            self._self_edit_scope_line(inv.active_scope),
        ]
        if inv.fresh:
            lines += [
                "",
                "[dim italic]Fresh install — no global or project items yet. "
                "The first file you create in one of the paths above becomes "
                "the first item in that scope.[/dim italic]",
            ]
        return "\n".join(lines)

    async def _enter_self_edit_with_message(self, msg: str) -> None:
        """Enter self-edit mode and submit the first message."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        if self._session is None:
            await chat_log.mount(
                Static("[yellow]No active session.[/yellow]", markup=True)
            )
            return

        # If already in self-edit, exit first so we get a truly fresh session
        if self._session.self_edit_mode:
            await self._session.toggle_self_edit_mode()

        await self._session.toggle_self_edit_mode()
        await chat_log.remove_children()
        await chat_log.mount(
            Static(self._self_edit_scope_banner(), markup=True)
        )
        self._wire_callbacks()
        self._update_status()

        if not msg:
            self._smart_scroll()
            return

        # Mount user message and send via normal path
        await chat_log.mount(
            Static(
                f"[bold #e6edf3]{escape(msg)}[/bold #e6edf3]",
                classes="user-message",
                markup=True,
            )
        )
        self._smart_scroll()
        self._send_and_drain(msg)

    def _apply_self_edit_profile(self, profile: AgentProfile) -> None:
        if self._session is None:
            return
        from taui.agent.loop import AgentLoop
        from taui.tools.executor import ToolExecutor

        registry = self._session._registry
        if profile.allowed_tools:
            available = [name for name in profile.allowed_tools if name in registry.names]
            registry = registry.subset(available) if available else registry
        executor = ToolExecutor(registry=registry, policy=self._session._executor._policy)
        if profile.provider:
            self._config.provider = profile.provider
        if profile.model:
            self._config.model = profile.model
        self._config.system_prompt = profile.prompt
        self._session.config = self._config
        self._session._system_prompt = profile.prompt

        stream_id = self._session._loop.stream_id
        loop = AgentLoop(
            agent_id=profile.id,
            llm=self._session._provider,
            executor=executor,
            stream=self._session._stream,
            system_prompt=profile.prompt,
            model=self._config.model,
            max_turns=self._config.max_turns,
        )
        loop.stream_id = stream_id
        self._session._replace_loop(loop)
        self._wire_callbacks()


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


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


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
