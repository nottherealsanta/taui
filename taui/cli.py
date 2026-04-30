"""
CLI REPL for taui.

Provides:
- Interactive prompt loop
- Live tool call and result display
- Interactive tool approval for writes/shell
- Slash commands via CommandRegistry
- Cost tracking per session
- Graceful Ctrl+C handling
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.config import Config
from taui.session import Session


# ── Colors ─────────────────────────────────────────────────────────────────────


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if _COLOR else text


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _COLOR else text


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if _COLOR else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if _COLOR else text


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if _COLOR else text


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m" if _COLOR else text


# ── REPL ───────────────────────────────────────────────────────────────────────


class Repl:
    """Interactive REPL loop."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._wire_callbacks()
        self._commands = self._build_commands()

    def _wire_callbacks(self) -> None:
        """Connect agent loop callbacks to CLI display."""
        loop = self._session._loop
        loop._on_tool_call = self._on_tool_call
        loop._on_tool_result = self._on_tool_result
        loop._on_approval = self._on_approval

        # Wire question tool callback
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

    async def _on_tool_call(self, call_id: str, name: str, arguments: dict) -> None:
        """Display a tool call as it starts."""
        args_summary = self._format_args(name, arguments)
        print(_cyan(f"  ▸ {name}") + _dim(f"({args_summary})"))
        # Observer hook
        await self._session.hooks.run("on_tool_call", name, arguments, self._session)

    async def _on_tool_result(
        self, call_id: str, name: str, content: str, is_error: bool
    ) -> None:
        """Display a tool result summary."""
        if is_error:
            # Show first line of error
            first_line = content.split("\n")[0][:120]
            print(_red(f"  ✗ {name}: {first_line}"))
        else:
            # Show a compact summary
            lines = content.split("\n")
            if len(lines) <= 3:
                for line in lines:
                    if line.strip():
                        print(_dim(f"    {line[:150]}"))
            else:
                print(_dim(f"    ({len(lines)} lines)"))
        # Observer hook
        await self._session.hooks.run("on_tool_result", name, content, is_error, self._session)

    async def _on_approval(self, call_id: str, name: str, arguments: dict) -> bool:
        """Prompt user for tool approval. Returns True if approved."""
        # Override hook — let extensions auto-approve/deny
        override = await self._session.hooks.first("on_approval", name, arguments, self._session)
        if override is not None:
            return override

        args_summary = self._format_args(name, arguments)
        print()
        print(_yellow(f"  ⚠ {name} requires approval"))
        print(_dim(f"    {args_summary}"))
        try:
            answer = input(_yellow("  Allow? [y/N] ")).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    async def _ask_question(
        self, question: str, options: list[str] | None
    ) -> str | None:
        """Handle a question from the agent."""
        print()
        print(_yellow(f"  ? {question}"))
        if options:
            for i, opt in enumerate(options, 1):
                print(_dim(f"    {i}. {opt}"))
            print(_dim("    (enter number or text)"))
        try:
            answer = input(_yellow("  > ")).strip()
            if not answer:
                return None
            # If options provided and answer is a number, map to option
            if options and answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            return answer
        except (EOFError, KeyboardInterrupt):
            return None

    @staticmethod
    def _format_args(name: str, arguments: dict) -> str:
        """Format tool arguments for display — compact and readable."""
        if not arguments:
            return ""
        match name:
            case "read":
                return arguments.get("path", "")
            case "write":
                path = arguments.get("path", "")
                content = arguments.get("content", "")
                lines = content.count("\n") + (1 if content else 0)
                return f"{path}, {lines} lines"
            case "edit":
                path = arguments.get("path", "")
                edits = arguments.get("edits", [])
                count = len(edits) if isinstance(edits, list) else "?"
                return f"{path}, {count} edit{'s' if count != 1 else ''}"
            case "glob":
                return arguments.get("pattern", "")
            case "grep":
                pat = arguments.get("pattern", "")
                inc = arguments.get("include", "")
                return f"/{pat}/" + (f" {inc}" if inc else "")
            case "bash":
                cmd = arguments.get("command", "")
                if len(cmd) > 80:
                    cmd = cmd[:77] + "..."
                return cmd
            case "git":
                op = arguments.get("operation", "")
                args = arguments.get("args", {})
                if args:
                    details = ", ".join(f"{k}={v}" for k, v in args.items())
                    return f"{op} ({details})"
                return op
            case "question":
                q = arguments.get("question", "")
                if len(q) > 60:
                    q = q[:57] + "..."
                return q
            case "sub_agent":
                task = arguments.get("task", "")
                if len(task) > 60:
                    task = task[:57] + "..."
                tools = arguments.get("tools")
                if tools:
                    return f"{task} [{', '.join(tools)}]"
                return task
            case "skills":
                op = arguments.get("operation", "")
                skill = arguments.get("skill", "")
                return f"{op} {skill}".strip()
            case "mcp":
                op = arguments.get("operation", "")
                server = arguments.get("server", "")
                tool = arguments.get("tool", "")
                parts = [op]
                if server:
                    parts.append(server)
                if tool:
                    parts.append(tool)
                return " ".join(parts)
            case _:
                parts = []
                for k, v in arguments.items():
                    sv = str(v)
                    if len(sv) > 40:
                        sv = sv[:37] + "..."
                    parts.append(f"{k}={sv}")
                return ", ".join(parts)

    async def run(self) -> None:
        """Main REPL loop."""
        self._print_banner()

        while True:
            try:
                user_input = self._prompt()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input.strip():
                continue

            # Slash commands
            if user_input.startswith("/"):
                if await self._handle_command(user_input):
                    continue
                else:
                    break  # /quit

            # Send to agent
            await self._send(user_input)

        await self._session.close()
        print(_dim("Goodbye."))

    def _print_banner(self) -> None:
        provider = self._session.provider_name
        model = self._session.model_name
        cwd = self._session.working_dir
        print()
        print(_bold("taui") + _dim(f"  {provider}/{model}"))
        print(_dim(f"cwd: {cwd}"))
        # Banner hooks (sync)
        for fn in self._session.hooks._hooks.get("banner", []):
            try:
                line = fn(self._session)
                if line:
                    print(_dim(line))
            except Exception:
                pass
        print(_dim("Type /help for commands, Ctrl+D to exit."))
        print()

    def _prompt(self) -> str:
        """Read user input. Supports multi-line with trailing backslash."""
        try:
            # Check for prompt hook override (sync hooks only)
            prompt_text = None
            for fn in self._session.hooks._hooks.get("prompt", []):
                try:
                    result = fn(self._session)
                    if result is not None:
                        prompt_text = result
                        break
                except Exception:
                    pass

            if prompt_text:
                line = input(prompt_text)
            elif self._session.extensions_mode:
                line = input(_yellow("⚙ > "))
            else:
                line = input(_green("> "))
        except EOFError:
            raise
        except KeyboardInterrupt:
            raise EOFError

        lines = [line]
        while lines[-1].endswith("\\"):
            lines[-1] = lines[-1][:-1]  # strip trailing backslash
            try:
                lines.append(input(_dim("... ")))
            except (EOFError, KeyboardInterrupt):
                break

        return "\n".join(lines)

    async def _handle_command(self, cmd: str) -> bool:
        """Handle a slash command. Returns True to continue, False to quit."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command in ("/quit", "/q", "/exit"):
            # In extensions mode, /q toggles extensions off instead of quitting
            if command == "/q" and self._session.extensions_mode:
                result = await self._commands.execute("/i")
                print(_yellow(result.output))
                self._rewire()
                return True
            return False

        # Dispatch through command registry
        result = await self._commands.execute(cmd)
        if result.error:
            print(_yellow(result.output))
        else:
            if self._session.extensions_mode:
                print(_yellow(result.output))
            else:
                print(_dim(result.output))

        # Rewire callbacks after session/mode changes
        action = result.metadata.get("action") if result.metadata else None
        if action == "extensions_on":
            print(_dim("/q to quit"))
            self._rewire()
        elif action in ("extensions_off", "new_session", "session_resumed"):
            self._rewire()

        return True

    async def _send(self, message: str) -> None:
        """Send a message and display the response.

        Tool calls and results are displayed live via callbacks.
        This method only shows the final text and usage summary.
        """
        print()
        try:
            result = await self._session.send(message)
        except KeyboardInterrupt:
            print(_yellow("\nCancelled."))
            return
        except Exception as exc:
            print(_red(f"\nError: {exc}"))
            return

        # Display final response (only if there were tool calls — otherwise
        # the on_text callback already printed intermediate text, but the
        # final response is the authoritative one)
        if result.text:
            print()
            print(result.text)

        # Display turn/usage summary
        turns = result.turns
        usage_parts: list[str] = []
        for tr in result.turn_results:
            if tr.usage:
                in_tok = tr.usage.get("input_tokens", 0)
                out_tok = tr.usage.get("output_tokens", 0)
                usage_parts.append(f"{in_tok}→{out_tok}")

        summary = _dim(f"[{turns} turn{'s' if turns != 1 else ''}")
        if usage_parts:
            summary += _dim(f" | tokens: {', '.join(usage_parts)}")
        tracker = self._session.cost_tracker
        if tracker.total_cost_usd > 0:
            summary += _dim(f" | ${tracker.total_cost_usd:.4f}")
        # Turn summary hooks (sync)
        for fn in self._session.hooks._hooks.get("turn_summary", []):
            try:
                extra = fn(result, self._session)
                if extra:
                    summary += _dim(f" | {extra}")
            except Exception:
                pass
        summary += _dim("]")
        print(f"\n{summary}\n")


# ── Entry point ────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> dict:
    """Minimal arg parsing — no external deps needed."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="taui",
        description="Agentic coding interface you can reshape.",
    )
    parser.add_argument(
        "-p", "--provider",
        choices=["copilot", "codex"],
        default=None,
        help="LLM provider (default: copilot)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="Model name (default: claude-sonnet-4.6)",
    )
    parser.add_argument(
        "-d", "--dir",
        default=None,
        help="Working directory (default: current directory)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        default=False,
        help="Start as a WebSocket JSON-RPC server (requires fastapi + uvicorn)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        default=False,
        help="Start the Textual terminal UI (requires textual)",
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="Optional initial message (non-interactive mode)",
    )

    args = parser.parse_args(argv)
    result: dict = {}
    if args.provider:
        result["provider"] = args.provider
    if args.model:
        result["model"] = args.model
    if args.dir:
        result["working_dir"] = Path(args.dir).resolve()
    if args.web:
        result["mode"] = "web"
    elif args.tui:
        result["mode"] = "tui"
    if args.message:
        result["initial_message"] = " ".join(args.message)
    return result


async def async_main(argv: list[str] | None = None) -> None:
    """Async entry point."""
    parsed = parse_args(argv)
    initial_message = parsed.pop("initial_message", None)
    parsed.pop("mode", None)  # mode handled in sync main()

    config = Config.load(**parsed)

    session = await Session.create(config)

    if initial_message:
        # Non-interactive: single message, print, exit
        repl = Repl(session)
        repl._print_banner()
        await repl._send(initial_message)
        await session.close()
    else:
        # Interactive REPL
        repl = Repl(session)
        await repl.run()


def main(argv: list[str] | None = None) -> None:
    """Sync entry point for console_scripts."""
    parsed = parse_args(argv)
    mode = parsed.get("mode")

    if mode == "web":
        config = Config.load(**{k: v for k, v in parsed.items() if k != "mode" and k != "initial_message"})
        try:
            import uvicorn  # noqa: F401
            import fastapi  # noqa: F401
        except ImportError:
            print("Web server requires: pip install 'taui[web]'  (or: pip install fastapi uvicorn websockets)", file=sys.stderr)
            return
        from taui.server.app import serve
        serve(config.working_dir, config=config)
        return

    if mode == "tui":
        config = Config.load(**{k: v for k, v in parsed.items() if k != "mode" and k != "initial_message"})
        try:
            import textual  # noqa: F401
        except ImportError:
            print("TUI requires: pip install 'taui[tui]'  (or: pip install textual)", file=sys.stderr)
            return
        from taui.tui import run_tui
        run_tui(config)
        return

    try:
        asyncio.run(async_main(argv))
    except KeyboardInterrupt:
        print()
