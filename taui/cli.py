"""
CLI REPL for taui.

Provides:
- Interactive prompt loop
- Live tool call and result display
- Interactive tool approval for writes/shell
- Slash commands (/help, /model, /clear, /quit)
- Graceful Ctrl+C handling
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

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


# ── Slash commands ─────────────────────────────────────────────────────────────

HELP_TEXT = """\
Commands:
  /help            Show this help
  /model [name]    Show or set the model
  /clear           Clear conversation history
  /quit            Exit taui

Shortcuts:
  Ctrl+C           Cancel current request
  Ctrl+D           Exit taui
"""


# ── REPL ───────────────────────────────────────────────────────────────────────


class Repl:
    """Interactive REPL loop."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._wire_callbacks()

    def _wire_callbacks(self) -> None:
        """Connect agent loop callbacks to CLI display."""
        loop = self._session._loop
        loop._on_tool_call = self._on_tool_call
        loop._on_tool_result = self._on_tool_result
        loop._on_approval = self._on_approval

    # ── Agent loop callbacks ──────────────────────────────────────────

    async def _on_tool_call(self, call_id: str, name: str, arguments: dict) -> None:
        """Display a tool call as it starts."""
        args_summary = self._format_args(name, arguments)
        print(_cyan(f"  ▸ {name}") + _dim(f"({args_summary})"))

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

    async def _on_approval(self, call_id: str, name: str, arguments: dict) -> bool:
        """Prompt user for tool approval. Returns True if approved."""
        args_summary = self._format_args(name, arguments)
        print()
        print(_yellow(f"  ⚠ {name} requires approval"))
        print(_dim(f"    {args_summary}"))
        try:
            answer = input(_yellow("  Allow? [y/N] ")).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

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
                if self._handle_command(user_input):
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
        print(_dim("Type /help for commands, Ctrl+D to exit."))
        print()

    def _prompt(self) -> str:
        """Read user input. Supports multi-line with trailing backslash."""
        try:
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

    def _handle_command(self, cmd: str) -> bool:
        """Handle a slash command. Returns True to continue, False to quit."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else None

        match command:
            case "/help" | "/h":
                print(HELP_TEXT)

            case "/model":
                if arg:
                    self._session.config.model = arg
                    self._session._loop._model = arg
                    print(_dim(f"Model set to {arg}"))
                else:
                    print(_dim(f"Current model: {self._session.model_name}"))

            case "/clear":
                self._session._loop._messages.clear()
                print(_dim("Conversation cleared."))

            case "/quit" | "/q" | "/exit":
                return False

            case _:
                print(_yellow(f"Unknown command: {command}. Type /help for options."))

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
        help="Model name (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "-d", "--dir",
        default=None,
        help="Working directory (default: current directory)",
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="Optional initial message (non-interactive mode)",
    )

    args = parser.parse_args(argv)
    result = {}
    if args.provider:
        result["provider"] = args.provider
    if args.model:
        result["model"] = args.model
    if args.dir:
        result["working_dir"] = Path(args.dir).resolve()
    if args.message:
        result["initial_message"] = " ".join(args.message)
    return result


async def async_main(argv: list[str] | None = None) -> None:
    """Async entry point."""
    parsed = parse_args(argv)
    initial_message = parsed.pop("initial_message", None)

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
    try:
        asyncio.run(async_main(argv))
    except KeyboardInterrupt:
        print()
