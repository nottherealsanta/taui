"""
CLI package for taui — full-screen terminal interface.

Public API:
    parse_args, async_main, main  — entry points
    CliApp (alias: Repl)          — the interactive application
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from taui.cli.app import CliApp, Repl
from taui.config import Config

__all__ = ["CliApp", "Repl", "parse_args", "async_main", "main"]


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
        help="Model name (auto-detected from models.dev if omitted)",
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
        "--login",
        action="store_true",
        default=False,
        help="Add or re-authenticate providers",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        default=False,
        dest="print_mode",
        help="Print mode: single prompt, print response, exit",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Suppress spinner and progress in non-interactive mode",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output events as JSON lines (JSONL)",
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
    if args.login:
        result["login"] = True
    if args.print_mode:
        result["print_mode"] = True
    if args.quiet:
        result["quiet"] = True
    if args.json:
        result["json_mode"] = True

    # Separate @file references from message words
    messages: list[str] = []
    file_contents: list[str] = []
    for word in (args.message or []):
        if word.startswith("@") and len(word) > 1:
            fpath = Path(word[1:])
            if fpath.is_file():
                try:
                    content = fpath.read_text()
                    file_contents.append(
                        f"\n```{fpath.name}\n{content}\n```\n"
                    )
                except (OSError, UnicodeDecodeError):
                    messages.append(word)
            else:
                messages.append(word)
        else:
            messages.append(word)

    # Detect stdin pipe and merge
    if not sys.stdin.isatty():
        try:
            stdin_data = sys.stdin.read()
            if stdin_data.strip():
                file_contents.append(
                    f"\n```stdin\n{stdin_data}\n```\n"
                )
                # Auto-enable print mode when piped
                if "print_mode" not in result:
                    result["print_mode"] = True
        except Exception:
            pass

    if messages or file_contents:
        parts = messages + file_contents
        result["initial_message"] = " ".join(
            p for p in parts if p
        )

    return result


async def async_main(
    argv: list[str] | None = None,
    parsed_override: dict | None = None,
) -> None:
    """Async entry point."""
    from taui.session import Session

    parsed = (
        parsed_override if parsed_override is not None
        else parse_args(argv)
    )
    initial_message = parsed.pop("initial_message", None)
    parsed.pop("mode", None)
    print_mode = parsed.pop("print_mode", False)
    quiet = parsed.pop("quiet", False)
    json_mode = parsed.pop("json_mode", False)

    config = Config.load(**parsed)
    session = await Session.create(config)

    if json_mode and initial_message:
        await _run_json_mode(session, initial_message)
    elif print_mode and initial_message:
        await _run_print_mode(session, initial_message, quiet=quiet)
    elif initial_message:
        repl = CliApp(session)
        repl._print_banner()
        await repl._send(initial_message)
        await session.close()
    else:
        repl = CliApp(session)
        await repl.run()


async def _run_print_mode(
    session, message: str, *, quiet: bool = False,
) -> None:
    """Single prompt → print response → exit."""
    try:
        result = await session.send(message)
        if result.text:
            print(result.text)
    except Exception as exc:
        if not quiet:
            print(f"Error: {exc}", file=sys.stderr)
    finally:
        await session.close()


async def _run_json_mode(session, message: str) -> None:
    """Stream events as JSONL to stdout."""
    try:
        result = await session.send(message)
        # Emit structured events
        for tr in result.turn_results:
            event = {
                "type": "turn",
                "turn": tr.turn,
                "usage": tr.usage,
                "tool_calls": [
                    {"name": tc.get("name"), "arguments": tc.get("arguments")}
                    for tc in (tr.metadata.get("tool_calls", []) if tr.metadata else [])
                ],
            }
            print(json.dumps(event))
        if result.text:
            print(json.dumps({"type": "text", "content": result.text}))
        print(json.dumps({
            "type": "summary",
            "turns": result.turns,
            "cost": session.cost_tracker.total_cost_usd,
            "input_tokens": session.cost_tracker.total_input_tokens,
            "output_tokens": session.cost_tracker.total_output_tokens,
        }))
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}))
    finally:
        await session.close()


def main(argv: list[str] | None = None) -> None:
    """Sync entry point for console_scripts."""
    parsed = parse_args(argv)
    mode = parsed.get("mode")

    if mode == "web":
        cfg_overrides = {
            k: v for k, v in parsed.items()
            if k != "mode" and k != "initial_message"
        }
        if "provider" not in cfg_overrides:
            from taui.llm_provider.auth import (
                get_saved_provider,
                prompt_provider_selection,
            )
            saved = get_saved_provider()
            if saved:
                cfg_overrides["provider"] = saved
            else:
                cfg_overrides["provider"] = prompt_provider_selection()
        config = Config.load(**cfg_overrides)
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError:
            print(
                "Web server requires: pip install 'taui[web]'"
                "  (or: pip install fastapi uvicorn websockets)",
                file=sys.stderr,
            )
            return
        from taui.server.app import serve
        serve(config.working_dir, config=config)
        return

    if mode == "tui":
        cfg_overrides = {
            k: v for k, v in parsed.items()
            if k != "mode" and k != "initial_message"
        }
        if "provider" not in cfg_overrides:
            from taui.llm_provider.auth import (
                get_saved_provider,
                prompt_provider_selection,
            )
            saved = get_saved_provider()
            if saved:
                cfg_overrides["provider"] = saved
            else:
                cfg_overrides["provider"] = prompt_provider_selection()
        config = Config.load(**cfg_overrides)
        try:
            import textual  # noqa: F401
        except ImportError:
            print(
                "TUI requires: pip install 'taui[tui]'"
                "  (or: pip install textual)",
                file=sys.stderr,
            )
            return
        from taui.tui import run_tui
        run_tui(config)
        return

    if parsed.pop("login", False):
        from taui.llm_provider.auth import prompt_provider_selection
        parsed["provider"] = prompt_provider_selection()
    elif "provider" not in parsed:
        from taui.llm_provider.auth import (
            get_saved_provider,
            prompt_provider_selection,
        )
        saved = get_saved_provider()
        if saved:
            parsed["provider"] = saved
        else:
            parsed["provider"] = prompt_provider_selection()

    try:
        asyncio.run(async_main(argv, parsed_override=parsed))
    except KeyboardInterrupt:
        print()
