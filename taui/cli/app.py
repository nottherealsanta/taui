"""
Line-by-line CLI REPL.

Uses prompt-toolkit PromptSession for input (completion, history) and
Rich Console + Live for output.  NOT a full-screen application — output
scrolls naturally in the terminal.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, merge_completers
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text

from taui.cli.completers import FileCompleter, SlashCompleter
from taui.cli.renderer import format_args
from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.session import Session

_AT_FILE_RE = re.compile(r"(?:^|(?<=\s))@(\S+)")


class CliApp:
    """Interactive line-by-line REPL."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._streaming = False
        self._stream_buffer = ""
        self._agent_working = False
        self._active_send: asyncio.Task | None = None
        self._queued: list[str] = []  # follow-up messages
        self._approval_future: asyncio.Future | None = None
        self._question_future: asyncio.Future | None = None
        self._console = Console()
        self._live: Live | None = None
        self._input_buffer = ""
        self._old_termios: list | None = None
        self._commands = self._build_commands()
        self._should_exit = False
        self._wire_callbacks()

    # ── Output helpers ────────────────────────────────────────────────

    def _print(self, text: str = "", style: str | None = None) -> None:
        """Print a line. Uses live.console when Live is active."""
        con = self._live.console if self._live else self._console
        if style:
            con.print(text, style=style, highlight=False)
        else:
            con.print(text, highlight=False)

    def _print_md(self, text: str) -> None:
        """Render markdown to the console."""
        con = self._live.console if self._live else self._console
        con.print(Markdown(text))

    def _status_line(self) -> str:
        """Build a one-line status summary."""
        parts: list[str] = []
        provider = self._session.provider_name
        model = self._session.model_name
        mode = " [ext]" if self._session.extensions_mode else ""
        verbose = "" if self._session.config.verbose_tools else " [quiet]"
        parts.append(f"{provider}/{model}{mode}{verbose}")

        tracker = self._session.cost_tracker
        total_in = tracker.total_input_tokens
        ctx_limit = self._get_context_limit()
        if total_in > 0 and ctx_limit > 0:
            pct = int(total_in * 100 / ctx_limit)
            parts.append(f"{pct}% ctx")
        elif total_in > 0:
            parts.append(f"{total_in:,} tokens")

        cost = tracker.total_cost_usd
        if cost > 0:
            parts.append(f"${cost:.4f}")

        return "  │  ".join(parts)

    def _get_context_limit(self) -> int:
        """Return the context window token limit for the current model."""
        if hasattr(self, "_ctx_limit_cache"):
            return self._ctx_limit_cache
        try:
            from taui.llm_provider.models import list_models
            models = list_models(self._session.config.provider)
            current = self._session.model_name
            for m in models:
                if m["id"] == current:
                    self._ctx_limit_cache = m.get("context", 0) or 0
                    return self._ctx_limit_cache
        except Exception:
            pass
        self._ctx_limit_cache = 0
        return 0

    # ── Prompt ────────────────────────────────────────────────────────

    def _get_prompt(self) -> FormattedText:
        """Build the prompt message."""
        if self._approval_future and not self._approval_future.done():
            return FormattedText([("bold fg:yellow", "[y/N] ")])
        if self._question_future and not self._question_future.done():
            return FormattedText([("bold fg:yellow", "  ? ")])

        for fn in self._session.hooks._hooks.get("prompt", []):
            try:
                result = fn(self._session)
                if result is not None:
                    return FormattedText([("bold", result)])
            except Exception:
                pass

        if self._session.extensions_mode:
            return FormattedText([("bold fg:ansigreen", "⚙ > ")])
        return FormattedText([("bold fg:ansigreen", "> ")])

    def _get_bottom_toolbar(self) -> str:
        """Bottom toolbar — shows status info."""
        return self._status_line()

    # ── Live display ──────────────────────────────────────────────────

    def _build_live_renderable(self) -> RenderableType:
        """Build the transient renderable shown while agent is working.

        Layout (bottom-anchored):
          [streaming markdown]
          ⠿ thinking...
          ─────────────────────
          copilot/model │ 12% ctx │ $0.01
          > user input▏
        """
        parts: list[RenderableType] = []
        if self._streaming and self._stream_buffer:
            parts.append(Markdown(self._stream_buffer))
        parts.append(Spinner("dots", text="thinking...", style="dim bold"))
        parts.append(Rule(style="dim"))
        parts.append(Text(self._status_line(), style="dim"))
        prompt_line = Text()
        prompt_line.append("> ", style="bold green")
        prompt_line.append(self._input_buffer)
        prompt_line.append("▏", style="dim")
        parts.append(prompt_line)
        return Group(*parts)

    def _start_live(self) -> None:
        """Start a Rich Live display for the agent's turn."""
        self._live = Live(
            self._build_live_renderable(),
            console=self._console,
            transient=True,
            refresh_per_second=8,
        )
        self._live.start()

    def _update_live(self) -> None:
        """Update the Live display with current streaming state."""
        if self._live:
            self._live.update(self._build_live_renderable())

    def _stop_live(self) -> None:
        """Stop the Live display."""
        if self._live:
            self._live.stop()
            self._live = None

    # ── Inline stdin reader (active during agent work) ────────────────

    def _start_stdin_reader(self) -> None:
        """Enable character-by-character stdin during agent work.

        Sets cbreak mode (no line buffering, no echo) with ISIG disabled
        so Ctrl-C is handled in ``_on_stdin_readable`` instead of raising
        SIGINT.
        """
        if not sys.stdin.isatty():
            return
        try:
            import termios
            import tty

            self._old_termios = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            # Disable ISIG so Ctrl-C doesn't raise SIGINT
            attrs = termios.tcgetattr(sys.stdin)
            attrs[3] &= ~termios.ISIG
            termios.tcsetattr(sys.stdin, termios.TCSANOW, attrs)
            asyncio.get_running_loop().add_reader(
                sys.stdin.fileno(), self._on_stdin_readable,
            )
        except Exception:
            self._old_termios = None

    def _stop_stdin_reader(self) -> None:
        """Restore normal terminal input mode."""
        if self._old_termios is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(sys.stdin.fileno())
        except Exception:
            pass
        try:
            import termios

            termios.tcsetattr(
                sys.stdin, termios.TCSADRAIN, self._old_termios,
            )
        except Exception:
            pass
        self._old_termios = None
        self._input_buffer = ""

    def _on_stdin_readable(self) -> None:
        """Handle raw keypresses during agent work."""
        try:
            data = os.read(sys.stdin.fileno(), 1024).decode(errors="ignore")
        except Exception:
            return

        i = 0
        while i < len(data):
            ch = data[i]
            i += 1

            if ch == "\x1b":  # Escape sequence — skip
                if i < len(data) and data[i] == "[":
                    i += 1
                    while i < len(data):
                        c = data[i]
                        i += 1
                        if "@" <= c <= "~":
                            break
                continue

            if ch in ("\r", "\n"):
                text = self._input_buffer.strip()
                self._input_buffer = ""
                if text:
                    self._session._loop.steer(text)
                    self._print(
                        f"  ↳ steering: {text}", style="dim italic",
                    )
            elif ch in ("\x7f", "\x08"):  # Backspace
                self._input_buffer = self._input_buffer[:-1]
            elif ch == "\x03":  # Ctrl-C
                self._input_buffer = ""
                if (
                    self._active_send
                    and not self._active_send.done()
                ):
                    self._active_send.cancel()
            elif ch == "\x15":  # Ctrl-U — clear line
                self._input_buffer = ""
            elif ch >= " ":  # Printable
                self._input_buffer += ch

        self._update_live()

    # ── Wiring ────────────────────────────────────────────────────────

    def _wire_callbacks(self) -> None:
        """Connect agent loop callbacks to CLI display."""
        loop = self._session._loop
        loop._on_tool_call = self._on_tool_call
        loop._on_tool_result = self._on_tool_result
        loop._on_approval = self._on_approval
        loop._on_text_delta = self._on_text_delta

        for name in self._session._registry.names:
            tool = self._session._registry.get(name)
            if hasattr(tool, "_ask") and tool.name == "question":
                tool._ask = self._ask_question

    def _rewire(self) -> None:
        """Re-attach callbacks after session/loop reset."""
        self._wire_callbacks()

    def _build_commands(self) -> CommandRegistry:
        """Build the slash command registry."""
        registry = CommandRegistry()
        register_builtin_commands(
            registry,
            get_session=lambda: self._session,
            get_tracker=lambda: self._session.cost_tracker,
            get_extensions=lambda: self._session._ext_registry,
        )
        return registry

    # ── Agent loop callbacks ──────────────────────────────────────────

    async def _on_tool_call(
        self, call_id: str, name: str, arguments: dict
    ) -> None:
        """Display a tool call as it starts."""
        if self._streaming:
            self._end_stream()
        args_summary = format_args(name, arguments)
        self._print(f"  ▸ {name}  {args_summary}", style="cyan")
        await self._session.hooks.run(
            "on_tool_call", name, arguments, self._session,
        )

    async def _on_tool_result(
        self, call_id: str, name: str, content: str, is_error: bool
    ) -> None:
        """Display a tool result summary."""
        if is_error:
            first_line = content.split("\n")[0][:120]
            self._print(f"  ✗ {name}: {first_line}", style="red")
        elif self._session.config.verbose_tools:
            lines = content.split("\n")
            shown = 0
            for line in lines:
                if line.strip():
                    self._print(f"    {line[:150]}", style="dim")
                    shown += 1
                    if shown >= 3:
                        remaining = len(lines) - shown
                        if remaining > 0:
                            self._print(
                                f"    ... ({remaining} more lines)",
                                style="dim",
                            )
                        break
            if shown == 0:
                self._print("    (empty)", style="dim")
        else:
            line_count = content.count("\n") + 1
            self._print(
                f"    ✓ {name} ({line_count} lines)", style="dim",
            )
        await self._session.hooks.run(
            "on_tool_result", name, content, is_error, self._session,
        )

    async def _on_approval(
        self, call_id: str, name: str, arguments: dict
    ) -> bool:
        """Prompt user for tool approval."""
        override = await self._session.hooks.first(
            "on_approval", name, arguments, self._session,
        )
        if override is not None:
            return override

        args_summary = format_args(name, arguments)
        self._print()
        self._print(f"  ⚠ {name} requires approval", style="yellow")
        self._print(f"    {args_summary}", style="dim")
        self._approval_future = asyncio.get_running_loop().create_future()
        try:
            return await self._approval_future
        finally:
            self._approval_future = None

    async def _ask_question(
        self, question: str, options: list[str] | None
    ) -> str | None:
        """Handle a question from the agent."""
        self._print()
        self._print(f"  ? {question}", style="yellow")
        if options:
            for i, opt in enumerate(options, 1):
                self._print(f"    {i}. {opt}")
            self._print("    (enter number or text)", style="dim")
        self._question_options = options
        self._question_future = asyncio.get_running_loop().create_future()
        try:
            answer = await self._question_future
            if not answer:
                return None
            if options and answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            return answer
        finally:
            self._question_future = None
            self._question_options = None

    def _end_stream(self) -> None:
        """End streaming text — stop Live and render final markdown."""
        self._stop_live()
        if self._stream_buffer:
            self._print_md(self._stream_buffer)
        self._streaming = False
        self._stream_buffer = ""

    def _on_text_delta(self, delta: str) -> None:
        """Accumulate streaming text tokens and update Live display."""
        if not self._streaming:
            self._streaming = True
            self._stream_buffer = ""
        self._stream_buffer += delta
        self._update_live()

    # ── Main run loop ─────────────────────────────────────────────────

    async def run(self) -> None:
        """Main REPL loop — line-by-line prompt session."""
        self._print_banner()

        history_path = Path.home() / ".cache" / "taui" / "prompt_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        prompt_session: PromptSession = PromptSession(
            history=FileHistory(str(history_path)),
            completer=FuzzyCompleter(merge_completers([
                SlashCompleter(
                    self._commands,
                    get_session=lambda: self._session,
                ),
                FileCompleter(self._session.working_dir),
            ])),
            complete_while_typing=False,
            multiline=False,
            bottom_toolbar=self._get_bottom_toolbar,
        )

        while not self._should_exit:
            try:
                text = await prompt_session.prompt_async(
                    self._get_prompt,
                )
            except EOFError:
                break
            except KeyboardInterrupt:
                if (
                    self._agent_working
                    and self._active_send
                    and not self._active_send.done()
                ):
                    self._active_send.cancel()
                    self._restore_queued_to_editor()
                    continue
                break

            text = text.strip()
            if not text:
                continue

            await self._dispatch(text)

        await self._session.close()

    async def _dispatch(self, text: str) -> None:
        """Route user input to the appropriate handler."""
        # Approval pending
        if self._approval_future and not self._approval_future.done():
            self._approval_future.set_result(
                text.lower() in ("y", "yes"),
            )
            return

        # Question pending
        if self._question_future and not self._question_future.done():
            self._question_future.set_result(text if text else None)
            return

        # Slash command
        if text.startswith("/"):
            should_continue = await self._handle_command(text)
            if not should_continue:
                self._should_exit = True
            return

        # Shell command
        if text.startswith("!"):
            await self._run_shell_command(text[1:])
            return

        # Steering: Enter while agent works
        if self._agent_working:
            self._session._loop.steer(text)
            self._print(f"  ↳ steering: {text}", style="dim italic")
            return

        # Normal message
        self._active_send = asyncio.create_task(
            self._send_and_drain(text)
        )
        try:
            await self._active_send
        except asyncio.CancelledError:
            pass
        finally:
            self._active_send = None

    # ── Send message ──────────────────────────────────────────────────

    async def _send_and_drain(self, message: str) -> None:
        """Send a message and then process any queued follow-ups."""
        message = self._resolve_at_files(message)
        await self._send(message)
        while self._queued:
            msg = self._queued.pop(0)
            self._print()
            self._print("  ↳ processing follow-up", style="dim")
            msg = self._resolve_at_files(msg)
            await self._send(msg)

    async def _send(self, message: str) -> None:
        """Send a message and display the response."""
        self._print()
        self._print(f"  ▶ {message}", style="bold")
        self._print()
        self._streaming = False
        self._stream_buffer = ""
        self._agent_working = True
        self._start_live()
        self._start_stdin_reader()

        try:
            result = await self._session.send(message)
        except asyncio.CancelledError:
            if self._streaming:
                self._end_stream()
            else:
                self._stop_live()
            self._print("Cancelled.", style="yellow")
            return
        except Exception as exc:
            if self._streaming:
                self._end_stream()
            else:
                self._stop_live()
            self._print(f"Error: {exc}", style="red bold")
            return
        finally:
            self._stop_stdin_reader()
            self._agent_working = False

        did_stream = self._streaming
        if did_stream:
            self._end_stream()
        else:
            self._stop_live()

        for tr in result.turn_results:
            if tr.metadata and tr.metadata.get("reasoning_text"):
                self._print()
                self._print(tr.metadata["reasoning_text"], style="dim")

        if result.text and not did_stream:
            self._print()
            self._print_md(result.text)

        # Turn summary
        turns = result.turns
        usage_parts: list[str] = []
        reasoning_tok_total = 0
        for tr in result.turn_results:
            if tr.usage:
                in_tok = tr.usage.get("input_tokens", 0)
                out_tok = tr.usage.get("output_tokens", 0)
                usage_parts.append(f"{in_tok}→{out_tok}")
                reasoning_tok_total += tr.usage.get(
                    "reasoning_tokens", 0,
                )

        summary_parts = [f"{turns} turn{'s' if turns != 1 else ''}"]
        if usage_parts:
            summary_parts.append(f"tokens: {', '.join(usage_parts)}")
        if reasoning_tok_total > 0:
            summary_parts.append(f"reasoning: {reasoning_tok_total}")
        tracker = self._session.cost_tracker
        if tracker.total_cost_usd > 0:
            summary_parts.append(f"${tracker.total_cost_usd:.4f}")
        for fn in self._session.hooks._hooks.get("turn_summary", []):
            try:
                extra = fn(result, self._session)
                if extra:
                    summary_parts.append(extra)
            except Exception:
                pass
        self._print()
        self._print(
            f"[{' | '.join(summary_parts)}]", style="dim",
        )
        self._print()

    # ── @file resolution ──────────────────────────────────────────────

    def _resolve_at_files(self, text: str) -> str:
        """Replace @path references with file content before sending."""
        root = self._session.working_dir

        def _replace(m: re.Match) -> str:
            rel = m.group(1)
            path = root / rel
            if not path.is_file():
                return m.group(0)
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError:
                return m.group(0)
            try:
                content = path.read_text()
            except (OSError, UnicodeDecodeError):
                return m.group(0)
            self._print(
                f"  📎 {rel} ({len(content)} chars)", style="dim",
            )
            return f"\n```{path.name}\n{content}\n```\n"

        return _AT_FILE_RE.sub(_replace, text)

    # ── Shell commands ────────────────────────────────────────────────

    async def _run_shell_command(self, cmd: str) -> None:
        """Run a shell command and send its output as a user message.

        ``!cmd`` — run command, send output to the agent.
        ``!!cmd`` — run command silently, just show output.
        """
        silent = cmd.startswith("!")
        if silent:
            cmd = cmd[1:]
        cmd = cmd.strip()
        if not cmd:
            return

        self._print(f"  $ {cmd}", style="bold")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._session.working_dir),
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode(errors="replace").rstrip()
        except Exception as exc:
            self._print(f"  ✗ shell error: {exc}", style="red")
            return

        if output:
            self._console.print(output)

        if not silent and output:
            msg = f"Output of `{cmd}`:\n```\n{output}\n```"
            self._active_send = asyncio.create_task(
                self._send_and_drain(msg)
            )
            try:
                await self._active_send
            except asyncio.CancelledError:
                pass
            finally:
                self._active_send = None

    # ── Follow-up queue ───────────────────────────────────────────────

    def _queue_followup(self, text: str) -> None:
        """Queue a follow-up message to be sent after agent finishes."""
        self._queued.append(text)
        n = len(self._queued)
        self._print(
            f"  ↳ follow-up queued ({n} pending)", style="dim",
        )

    def _restore_queued_to_editor(self) -> None:
        """Clear queued follow-ups."""
        if not self._queued:
            return
        self._queued.clear()
        self._session._loop._steering_queue.clear()
        self._print("  ↳ cleared queued messages", style="dim")

    # ── Banner ────────────────────────────────────────────────────────

    def _print_banner(self) -> None:
        for fn in self._session.hooks._hooks.get("banner", []):
            try:
                line = fn(self._session)
                if line:
                    self._print(line)
            except Exception:
                pass
        self._print(self._status_line(), style="dim")
        self._print(
            "/help for commands, tab for completion, ctrl+d to exit.",
            style="dim",
        )
        self._print()

    # ── Commands ──────────────────────────────────────────────────────

    async def _handle_command(self, cmd: str) -> bool:
        """Handle a slash command. Returns True to continue, False to quit."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command in ("/quit", "/q", "/exit"):
            if command == "/q" and self._session.extensions_mode:
                result = await self._commands.execute("/i")
                self._print(result.output)
                self._rewire()
                return True
            return False

        result = await self._commands.execute(cmd)
        self._print(result.output)

        action = (
            result.metadata.get("action") if result.metadata else None
        )
        if action == "extensions_on":
            self._print("/q to quit", style="dim")
            self._rewire()
        elif action in (
            "extensions_off", "new_session", "session_resumed",
        ):
            self._rewire()

        return True


# Backwards compatibility alias
Repl = CliApp
