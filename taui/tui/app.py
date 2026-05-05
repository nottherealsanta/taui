"""Main Textual application for taui."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, estimate_total_tokens
from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.config import Config
from taui.session import Session
from taui.tui.messages import StreamReasoningDelta, StreamTextDelta, ToolEnded, ToolStarted
from taui.tui.screens.context_breakdown import ContextBreakdownScreen
from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.approval import ApprovalPrompt
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.completion_dropdown import CompletionDropdown
from taui.tui.widgets.info_bar import InfoBar
from taui.tui.widgets.questions_panel import QuestionSpec, QuestionsPanel
from taui.tui.widgets.sidebar import Sidebar
from taui.tui.widgets.self_edit import SelfEditView
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
    #chat-log {
        height: 1fr;
        padding: 1 2;
        scrollbar-size: 0 0;
    }
    .user-message {
        background: $surface;
        padding: 1 2;
        margin: 1 0 0 0;
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
        margin: 1 0;
    }
    Markdown H1 { color: $text; text-style: bold; }
    Markdown H2 { color: $text; text-style: bold; }
    Markdown H3 { color: $text; text-style: bold; }
    Markdown H4 { color: $text; }
    Markdown H5 { color: $text; }
    Markdown H6 { color: $text-muted; }
    #self-edit {
        layer: overlay;
        dock: top;
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+n", "new_chat", "New session"),
        ("ctrl+c", "cancel_request", "Cancel"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+x", "show_context", "Context"),
        ("ctrl+i", "open_self_edit", "Self-Edit"),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._config = config or Config.load()
        self._session: Session | None = None
        self._is_processing = False

        # Tool FIFO tracking (from archive pattern)
        self._tool_counter = 0
        self._pending_tool_keys: dict[str, list[str]] = {}
        self._active_tool_widgets: dict[str, ToolStatusWidget] = {}
        self._current_tool_section: Vertical | None = None

        # Streaming state
        self._current_response: AgentResponse | None = None
        self._current_reasoning: Static | None = None
        self._reasoning_buf: str = ""
        self._spinner_task: asyncio.Task | None = None
        self._streamed_text: bool = False

        # Queue for follow-up messages
        self._queued: list[str] = []
        self._pending_indicators: list[tuple[str, str]] = []
        self._active_questions_panel: QuestionsPanel | None = None
        self._self_edit_mode = False

        # History persistence
        self._history_file = Path.home() / ".cache" / "taui" / "prompt_history"
        self._history: list[str] = []

    LAYERS = ("default", "overlay")

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-layout"):
            yield Sidebar(self._config.working_dir)
            with Vertical(id="chat-area"):
                with VerticalScroll(id="chat-log"):
                    pass
                yield CompletionDropdown(id="completion-dropdown")
                yield ChatInput(
                    id="chat-input",
                    language=None,
                    show_line_numbers=False,
                )
                yield InfoBar()

    async def on_mount(self) -> None:
        self._session = await Session.create(self._config)
        self._wire_callbacks()
        self._commands = self._build_commands()
        self._update_status()

        # Load history
        self._load_history()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.load_history(self._history)
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
        )
        return registry

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
        )

    # ── Agent callbacks ───────────────────────────────────────────────

    def _wire_callbacks(self) -> None:
        assert self._session is not None
        loop = self._session._loop
        loop._on_tool_call = self._on_tool_call
        loop._on_tool_result = self._on_tool_result
        loop._on_text = self._on_text
        loop._on_text_delta = self._on_text_delta_sync
        loop._on_reasoning_delta = self._on_reasoning_delta_sync
        loop._on_approval = self._on_approval

        # Wire batch-question callback
        loop._on_questions_batch = self._on_questions_batch

    async def _on_tool_call(
        self, call_id: str, name: str, arguments: dict
    ) -> None:
        self._tool_counter += 1
        tool_key = f"{name}_{self._tool_counter}"
        self._pending_tool_keys.setdefault(name, []).append(tool_key)
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        self.post_message(ToolStarted(tool_key, name, args_short))

        if self._session:
            await self._session.hooks.run(
                "on_tool_call", name, arguments, self._session
            )

    async def _on_tool_result(
        self, call_id: str, name: str, content: str, is_error: bool
    ) -> None:
        # FIFO: pop oldest key for this tool name
        keys = self._pending_tool_keys.get(name, [])
        if keys:
            tool_key = keys.pop(0)
        else:
            # Fallback: find any active widget with this name prefix
            tool_key = next(
                (k for k in self._active_tool_widgets if k.startswith(name)),
                f"{name}_unknown",
            )
        self.post_message(ToolEnded(tool_key, name, content, is_error))

        if self._session:
            await self._session.hooks.run(
                "on_tool_result", name, content, is_error, self._session
            )

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

    async def _on_questions_batch(
        self, specs: list[tuple[str, list[str] | None]]
    ) -> list[str | None]:
        """Show a QuestionsPanel above the chat input and wait for answers."""
        q_specs = [QuestionSpec(q, opts) for q, opts in specs]
        chat_area = self.query_one("#chat-area", Vertical)
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        panel = QuestionsPanel(q_specs)
        self._active_questions_panel = panel
        try:
            await chat_area.mount(panel, before=chat_input)
            self._smart_scroll()
            return await panel.wait_for_answers()
        finally:
            if panel.is_mounted:
                await panel.remove()
            if self._active_questions_panel is panel:
                self._active_questions_panel = None
            chat_input.disabled = False
            chat_input.focus()

    async def _on_approval(
        self, call_id: str, name: str, arguments: dict
    ) -> bool:
        """Show approval prompt and wait for user response."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        prompt = ApprovalPrompt(name, args_short)
        await chat_log.mount(prompt)
        self._smart_scroll()
        return await prompt.wait_for_response()

    # ── Message handlers for tool events ──────────────────────────────

    @on(ToolStarted)
    async def handle_tool_started(self, event: ToolStarted) -> None:
        # Finalize any current response before tool section
        await self._finalize_response()

        chat_log = self.query_one("#chat-log", VerticalScroll)
        if self._current_tool_section is None:
            self._current_tool_section = Vertical(classes="tool-section")
            await chat_log.mount(self._current_tool_section)

        widget = ToolStatusWidget(event.tool_name, event.args_str)
        await self._current_tool_section.mount(widget)
        self._active_tool_widgets[event.tool_key] = widget

        # Update spinner to show tool name
        self.query_one(InfoBar).set_status(f"Running {event.tool_name}...")

    @on(ToolEnded)
    async def handle_tool_ended(self, event: ToolEnded) -> None:
        widget = self._active_tool_widgets.pop(event.tool_key, None)
        if widget:
            if event.is_error:
                await widget.fail(event.result)
            else:
                await widget.complete(event.result)

        # Reset spinner text
        self.query_one(InfoBar).set_status("Thinking...")

    # ── Streaming text handler ────────────────────────────────────────

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

        if text.startswith("/"):
            await self._handle_command(text)
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

        # Start spinner
        spinner = self.query_one(InfoBar)
        self._spinner_task = asyncio.create_task(spinner.start())

        self._current_tool_section = None
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
            spinner.stop()
            if self._spinner_task and not self._spinner_task.done():
                self._spinner_task.cancel()
            self._current_tool_section = None

    async def _finalize_response(self) -> None:
        """Finalize the current streaming response if any."""
        if self._current_response:
            await self._current_response.finalize()
            self._current_response = None
            # Only reset tool section when an actual response was finalized,
            # so the next tool section starts below the new text.
            self._current_tool_section = None
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
            if command == "/q" and self._self_edit_mode:
                await self.action_close_self_edit()
                return
            await self.action_quit_app()
            return

        if command == "/clear":
            await chat_log.remove_children()
            return

        result = await self._commands.execute(cmd)
        style = "yellow" if (result.error or (
            self._session and self._session.extensions_mode
        )) else "dim"
        await chat_log.mount(
            Static(f"[{style}]{result.output}[/{style}]", markup=True)
        )

        action = result.metadata.get("action") if result.metadata else None
        if action == "debug_questions":
            self.run_worker(
                self._debug_questions(chat_log),
                name="debug_questions",
                group="debug",
                exclusive=True,
            )
        if action == "extensions_on":
            await chat_log.mount(
                Static("[dim]/q to quit extensions[/dim]", markup=True)
            )
        if action == "self_edit_open":
            await self.action_open_self_edit()
        if action in (
            "extensions_on", "extensions_off", "new_session", "session_resumed"
        ):
            self._wire_callbacks()
            self._update_status()
        if action == "session_resumed":
            await self._render_replay()

    async def _debug_questions(self, chat_log: VerticalScroll) -> None:
        """Exercise the real question panel UI with deterministic sample data."""
        try:
            answers = await self._on_questions_batch(
                [
                    (
                        "Choose a deployment target",
                        [
                            "Local dev server (Recommended)",
                            "Staging environment",
                            "Production with dry-run",
                        ],
                    ),
                    (
                        "Pick a follow-up action",
                        [
                            "Open the diff",
                            "Run tests (Recommended)",
                            "Skip verification",
                        ],
                    ),
                ]
            )
        except asyncio.CancelledError:
            await chat_log.mount(
                Static("[dim]Debug questions cancelled.[/dim]", markup=True)
            )
            self._smart_scroll()
            raise
        else:
            rendered = ", ".join(answer or "<custom empty>" for answer in answers)
            await chat_log.mount(
                Static(
                    f"[dim]Debug answers: {escape(rendered)}[/dim]",
                    markup=True,
                )
            )
            self._smart_scroll()

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
        if self._self_edit_mode:
            await self.action_close_self_edit()
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
        if self._active_questions_panel is not None:
            panel = self._active_questions_panel
            if panel._future and not panel._future.done():
                panel._future.cancel()
            return
        if self._is_processing:
            # Clear queues
            self._queued.clear()
            if self._session:
                self._session._loop._steering_queue.clear()
            # Cancel the worker
            self.workers.cancel_all()

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle()

    async def action_show_context(self) -> None:
        if not self._session:
            return
        messages = self._session._loop._messages
        self.push_screen(ContextBreakdownScreen(messages))

    async def action_open_self_edit(self) -> None:
        if self._self_edit_mode:
            return
        self._self_edit_mode = True
        if self._session:
            await self._session.new_session()
            self._wire_callbacks()
            self._update_status()
        await self.query_one("#chat-log", VerticalScroll).remove_children()
        await self.mount(
            SelfEditView(config=self._config, session=self._session, id="self-edit")
        )
        self.query_one("#chat-input", ChatInput).disabled = True
        self.query_one("#completion-dropdown", CompletionDropdown).styles.display = "none"

    async def action_close_self_edit(self) -> None:
        if not self._self_edit_mode:
            return
        self._self_edit_mode = False
        try:
            await self.query_one("#self-edit", SelfEditView).remove()
        except NoMatches:
            pass
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.disabled = False
        chat_input.focus()
        self.query_one("#completion-dropdown", CompletionDropdown).styles.display = "block"

    @on(Sidebar.Dismiss)
    def handle_sidebar_dismiss(self, event: Sidebar.Dismiss) -> None:
        self.query_one("#chat-input", ChatInput).focus()


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s
