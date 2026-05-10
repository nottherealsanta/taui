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
from taui.tui.screens.session_picker import SessionPickerScreen
from taui.tui.tool_controller import ToolController
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.info_bar import InfoBar, _agent_color
from taui.tui.widgets.self_edit_panel import SelfEditPanel
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.spinner import ActivityProgress

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
    .user-message {
        background: $surface;
        padding: 1 2;
        margin: 1 0 1 0;
    }
    .tool-section {
        height: auto;
        padding: 0 2;
        margin: 0;
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
    .replay-tool {
        color: $text-muted;
        padding: 0 2;
        margin: 0;
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

        # Queue for follow-up messages
        self._queued: list[str] = []
        self._pending_indicators: list[tuple[str, str]] = []

        # History persistence
        self._history_file = Path.home() / ".cache" / "taui" / "prompt_history"
        self._history: list[str] = []
        self._self_edit_mode = False

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
                yield SelfEditPanel(
                    self._config,
                    SelfEditStore(self._config.working_dir),
                    self._empty_registry(),
                    id="self-edit-panel",
                )
                with VerticalScroll(id="chat-log"):
                    pass
                yield Info2(id="info2")
                with Vertical(id="chat-container"):
                    yield ChatInput(
                        id="chat-input",
                        language=None,
                        show_line_numbers=False,
                    )
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
        self.query_one(ActivityProgress).stop()
        self.run_worker(
            self._initialize_session(),
            name="session_init",
            group="startup",
            exclusive=True,
            exit_on_error=False,
        )

    async def _initialize_session(self) -> None:
        try:
            self._session = await Session.create(self._config)
        except Exception as exc:
            logger.exception("Failed to create session")
            self._session_initializing = False
            await self._show_startup_error(exc)
            return

        if not self._config.session_id:
            self._apply_default_agent_profile()
        self._configure_self_edit_panel()
        self._wire_callbacks()
        self._update_status()
        self._session_initializing = False

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
        chat_input.set_self_edit_completer(None)
        # Set up command completions
        completions = []
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
        chat_input.can_submit = True
        chat_input.focus()

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

    def _expand_file_refs(self, text: str) -> str:
        """Expand @path references to file contents."""
        words = text.split()
        result: list[str] = []
        for word in words:
            if word.startswith("@") and len(word) > 1:
                fpath = Path(word[1:])
                if not fpath.is_absolute():
                    fpath = self._config.working_dir / fpath
                if fpath.is_file():
                    try:
                        content = fpath.read_text()
                        result.append(f"\n```{fpath.name}\n{content}\n```\n")
                        continue
                    except (OSError, UnicodeDecodeError):
                        pass
            result.append(word)
        return " ".join(result)

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

    def _configure_self_edit_panel(self) -> None:
        if self._session is None:
            return
        try:
            panel = self.query_one("#self-edit-panel", SelfEditPanel)
        except Exception:
            return
        if not hasattr(self._session, "_registry"):
            return
        panel.set_registry(self._session._registry)
        panel.set_current_agent(str(getattr(self._session._loop, "agent_id", "") or ""))

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

    # ── Streaming text handlers ───────────────────────────────────────

    @on(StreamTextDelta)
    async def handle_stream_text(self, event: StreamTextDelta) -> None:
        """Handle incoming text deltas — stream into AgentResponse widget."""
        # Finalize reasoning block when regular text starts arriving
        if self._current_reasoning is not None:
            self._current_reasoning = None
        if self._current_response is None:
            chat_log = self.query_one("#chat-log", VerticalScroll)
            self._current_response = AgentResponse()
            await chat_log.mount(self._current_response)
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
            chat_log = self.query_one("#chat-log", VerticalScroll)
            self._current_reasoning = Static(
                f"[dim italic]{escape(display)}[/dim italic]",
                classes="reasoning-text",
                markup=True,
            )
            await chat_log.mount(self._current_reasoning)
        else:
            self._current_reasoning.update(
                f"[dim italic]{escape(display)}[/dim italic]"
            )
        self._smart_scroll()

    # ── Input handling ────────────────────────────────────────────────

    @on(ChatInput.Submitted)
    async def handle_input(self, event: ChatInput.Submitted) -> None:
        text = event.value

        if self._self_edit_mode:
            panel = self.query_one("#self-edit-panel", SelfEditPanel)
            await panel.run_verb(text)
            return

        if text.startswith("/"):
            await self._handle_command(text)
            return

        if self._session is None:
            chat_log = self.query_one("#chat-log", VerticalScroll)
            message = (
                "Session is still starting."
                if self._session_initializing
                else "No session is active. Fix auth/network access and restart, or run /login."
            )
            await chat_log.mount(
                Static(
                    f"[yellow]{escape(message)}[/yellow]",
                    markup=True,
                )
            )
            self._smart_scroll()
            return

        # Save to history
        self._save_to_history(text)

        # Expand @file references
        text = self._expand_file_refs(text)

        if self._is_processing:
            if event.queue:
                # Alt+Enter while busy → queue
                self._queued.append(text)
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
        await chat_log.mount(
            Static(
                f"[bold #e6edf3]{display_text}[/bold #e6edf3]",
                classes="user-message",
                markup=True,
            )
        )
        self._smart_scroll()
        self._send_and_drain(text)

    @on(ChatInput.AgentCycleRequested)
    async def handle_agent_cycle_requested(
        self,
        event: ChatInput.AgentCycleRequested,
    ) -> None:
        self._cycle_agent_profile()

    async def _show_indicator(self, mode: str, text: str) -> None:
        """Show a steer/queue indicator in the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        if mode == "s":
            await chat_log.mount(
                Static(
                    f"[dim]  s> {escape(text)}[/dim]",
                    classes="steer-indicator",
                    markup=True,
                )
            )
        else:
            await chat_log.mount(
                Static(
                    f"[#f5a524]  q> {escape(text)}[/#f5a524]",
                    classes="queue-indicator",
                    markup=True,
                )
            )
        self._smart_scroll()


    # ── Send message and drain queue ──────────────────────────────────

    @work(exclusive=True)
    async def _send_and_drain(self, text: str) -> None:
        assert self._session is not None
        self._set_busy(True)

        try:
            await self._do_send(text)

            # Drain queued messages
            while self._queued:
                msg = self._queued.pop(0)
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
                await self._do_send(msg)
        finally:
            self._set_busy(False)

    async def _do_send(self, text: str) -> None:
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

        try:
            result = await self._session.send(text)

            # Finalize any streaming response
            await self._finalize_response()

            # If no streaming happened (fallback), show response as markdown
            if result.text and not self._streamed_text:
                chat_log = self.query_one("#chat-log", VerticalScroll)
                md = Markdown(result.text)
                await chat_log.mount(md)

            # Turn summary
            chat_log = self.query_one("#chat-log", VerticalScroll)
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
                await chat_log.mount(
                    Static(summary, classes="turn-summary", markup=True)
                )

            self._update_status()
            self._smart_scroll()
        except asyncio.CancelledError:
            chat_log = self.query_one("#chat-log", VerticalScroll)
            await chat_log.mount(
                Static("[dim]Request cancelled.[/dim]", markup=True)
            )
        except Exception as exc:
            chat_log = self.query_one("#chat-log", VerticalScroll)
            await chat_log.mount(
                Static(f"[red]Error: {exc}[/red]", markup=True)
            )
        finally:
            progress.stop()
            self._tool_ctrl.reset_section()

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

    # ── Smart scroll ──────────────────────────────────────────────────

    def _smart_scroll(self) -> None:
        """Scroll to bottom only if content exceeds the visible area."""
        try:
            chat_log = self.query_one("#chat-log", VerticalScroll)
        except NoMatches:
            return
        if chat_log.virtual_size.height > chat_log.size.height:
            chat_log.scroll_end(animate=False)

    # ── Slash commands ────────────────────────────────────────────────

    async def _handle_command(self, cmd: str) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command in ("/quit", "/q", "/exit"):
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

        if command in ("/i", "/self-edit"):
            await self.action_enter_self_edit()
            return

        if command == "/clear":
            await chat_log.remove_children()
            return

        result = await self._commands.execute(cmd)
        action = result.metadata.get("action") if result.metadata else None
        if action == "session_picker":
            sessions = result.metadata.get("sessions", [])
            if sessions:
                await self._open_session_picker(sessions)
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

        if action not in ("self_edit_open", "model_changed"):
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
        if action == "self_edit_open":
            await self.action_enter_self_edit()
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

        from taui.agent.context import compact_messages, estimate_total_tokens

        loop = self._session._loop
        before_tokens = estimate_total_tokens(loop._messages)
        removed = compact_messages(loop._messages)
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

    async def _open_session_picker(self, sessions: list[dict]) -> None:
        """Open the session picker and resume the selected session."""
        selected = await self.push_screen_wait(SessionPickerScreen(sessions))
        if selected is None:
            return
        await self._resume_session(selected)

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
        for item in self._session.replay_items:
            if item.kind == "user":
                await chat_log.mount(
                    Static(
                        f"[bold #e6edf3]{escape(item.text)}[/bold #e6edf3]",
                        classes="user-message",
                        markup=True,
                    )
                )
            elif item.kind == "assistant":
                await chat_log.mount(Markdown(item.text))
            elif item.kind == "tool_call":
                args = ", ".join(
                    f"{key}={_trunc(str(value))}"
                    for key, value in (item.arguments or {}).items()
                )
                suffix = f" [dim]{escape(args)}[/dim]" if args else ""
                await chat_log.mount(
                    Static(
                        f"[#6BB6FF]{escape(item.name)}[/#6BB6FF]{suffix}",
                        classes="replay-tool",
                        markup=True,
                    )
                )
            elif item.kind == "tool_result":
                style = "#f97583" if item.is_error else "dim"
                preview = _trunc(" ".join(item.text.strip().split()), 180)
                await chat_log.mount(
                    Static(
                        f"[{style}]  {escape(preview)}[/{style}]",
                        classes="replay-tool",
                        markup=True,
                    )
                )
            elif item.kind == "error":
                await chat_log.mount(
                    Static(
                        f"[red]Error: {escape(item.text)}[/red]",
                        markup=True,
                    )
                )
        self._smart_scroll()

    # ── Actions ───────────────────────────────────────────────────────

    async def action_quit_app(self) -> None:
        if self._session:
            await self._session.close()
        self.exit()

    async def action_new_chat(self) -> None:
        if self._session:
            await self._session.new_session()
            self._wire_callbacks()
            chat_log = self.query_one("#chat-log", VerticalScroll)
            await chat_log.remove_children()
            self._update_status()
            await chat_log.mount(
                Static("[dim]New session started.[/dim]", markup=True)
            )

    async def action_cancel_request(self) -> None:
        if self._approval_ctrl.has_active_panel():
            self._approval_ctrl.cancel_active_panel()
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
        if self._session is None:
            return

        if self._self_edit_mode:
            await self.action_exit_self_edit()
            return

        self._session._loop.pause()
        self._self_edit_mode = True
        panel = self.query_one("#self-edit-panel", SelfEditPanel)
        panel.set_registry(self._session._registry)
        panel.set_current_agent(str(getattr(self._session._loop, "agent_id", "") or ""))
        panel.show_panel()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.set_self_edit_completer(panel.complete)
        chat_input.border_title = "self-edit"
        chat_input.focus()
        await panel.run_verb("/help")

    async def action_exit_self_edit(self) -> None:
        if self._session is None:
            return
        panel = self.query_one("#self-edit-panel", SelfEditPanel)
        panel.hide_panel()
        self._self_edit_mode = False
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.set_self_edit_completer(None)
        chat_input.border_title = None
        self._session._loop.resume()
        self._wire_callbacks()
        self._update_status()
        chat_input.focus()
        self.notify("Agents resumed", timeout=2)

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
        self._configure_self_edit_panel()


    def on_key(self, event: Key) -> None:
        """Intercept keys when Info2 is in model/agent mode."""
        from taui.tui.widgets.info2 import Info2Mode

        info2 = self.query_one("#info2", Info2)
        if not info2.is_active:
            return
        if info2.mode == Info2Mode.COMPLETIONS:
            return  # ChatInput handles completion keys
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
            info2.hide()

    async def action_escape(self) -> None:
        info2 = self.query_one("#info2", Info2)
        if info2.is_active:
            info2.hide()
            return
        if self._self_edit_mode:
            panel = self.query_one("#self-edit-panel", SelfEditPanel)
            await panel.request_exit()

    @on(SelfEditPanel.Activated)
    def handle_self_edit_agent_activated(self, event: SelfEditPanel.Activated) -> None:
        self._apply_self_edit_profile(event.profile)
        self._update_status()

    @on(SelfEditPanel.ExitRequested)
    async def handle_self_edit_exit_requested(
        self, event: SelfEditPanel.ExitRequested
    ) -> None:
        await self.action_exit_self_edit()

    @on(SelfEditPanel.Saved)
    def handle_self_edit_saved(self, event: SelfEditPanel.Saved) -> None:
        if self._session:
            self._session._loop.update_system_prompt(self._config.system_prompt)
            self._configure_self_edit_panel()

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
