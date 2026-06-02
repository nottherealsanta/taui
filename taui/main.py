"""Entry point for taui — launches the Textual TUI."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
from pathlib import Path


def _build_resume_command(launcher_base: str, session_id: str) -> str:
    """Assemble a resume command from a launcher base plus --session <id>."""
    return f"{launcher_base} --session {shlex.quote(session_id)}"


def _parse_uvx_launcher(tokens: list[str]) -> str | None:
    """Recognize simple uvx launches from a parent command's argv tokens.

    Accepts both ``uvx taui...`` and uv's normalized ``uv tool uvx taui...``
    shapes. Returns "uvx taui" or "uvx taui@latest" only when the package token
    is exactly ``taui`` or starts with ``taui@``.
    """
    if not tokens:
        return None

    first = os.path.basename(tokens[0])

    if first == "uvx":
        pkg_tokens = tokens[1:]
    elif first == "uv":
        # uv's normalized form: uv tool uvx taui...
        if len(tokens) >= 3 and tokens[1] == "tool" and tokens[2] == "uvx":
            pkg_tokens = tokens[3:]
        else:
            return None
    else:
        return None

    if not pkg_tokens:
        return None

    package = pkg_tokens[0]
    if package == "taui":
        return "uvx taui"
    if package.startswith("taui@"):
        return f"uvx {package}"
    return None


def _detect_uvx_launcher() -> str | None:
    """Detect a simple uvx launch by inspecting the parent process command line.

    Returns "uvx taui" or "uvx taui@latest" for the recognized simple forms,
    or None when detection fails, ps is unavailable, parsing fails, or the
    launch shape is more complex.
    """
    try:
        ppid = os.getppid()
        completed = subprocess.run(
            ["ps", "-o", "args=", "-p", str(ppid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    cmdline = completed.stdout.strip()
    if not cmdline:
        return None

    try:
        tokens = shlex.split(cmdline)
    except ValueError:
        return None

    return _parse_uvx_launcher(tokens)


def _setup_logging() -> None:
    """Configure logging to write to ~/.taui/.logs."""
    log_dir = Path.home() / ".taui"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / ".logs"

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


def parse_args(argv: list[str] | None = None) -> dict:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="taui",
        description="Agentic coding interface you can reshape.",
    )
    from taui.llm_provider.registry import get_provider_names

    parser.add_argument(
        "-p", "--provider",
        choices=get_provider_names(),
        default=None,
        help="LLM provider (default: copilot)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="Model name",
    )
    parser.add_argument(
        "-d", "--dir",
        default=None,
        help="Working directory (default: current directory)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Resume a previous session by id",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        default=False,
        help="Add or re-authenticate providers",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        default=False,
        help="Show version and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Start with embedded MCP debug server for external control",
    )
    parser.add_argument(
        "--debug-socket",
        default=None,
        help="Path for the debug server's Unix socket (default: /tmp/taui-debug-{pid}.sock)",
    )

    args = parser.parse_args(argv)
    result: dict = {}

    if args.version:
        result["version"] = True
    if args.provider:
        result["provider"] = args.provider
    if args.model:
        result["model"] = args.model
    if args.dir:
        result["working_dir"] = Path(args.dir).resolve()
    if args.session:
        result["session_id"] = args.session
    if args.login:
        result["login"] = True
    if args.debug:
        result["debug"] = True
    if args.debug_socket:
        result["debug_socket"] = args.debug_socket

    return result


def main(argv: list[str] | None = None) -> None:
    """Sync entry point for console_scripts."""
    _setup_logging()
    parsed = parse_args(argv)

    if parsed.pop("version", False):
        from importlib.metadata import version
        try:
            ver = version("taui")
        except Exception:
            ver = "dev"
        print(f"taui {ver}")
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

    debug = parsed.pop("debug", False)
    debug_socket = parsed.pop("debug_socket", None)

    from taui.config import Config
    config = Config.load(**parsed)

    from taui.tui import run_tui
    session_id = run_tui(config, debug=debug, debug_socket=debug_socket)
    if session_id:
        from rich.console import Console

        launcher_base = _detect_uvx_launcher() or "uv run taui"
        resume_command = _build_resume_command(launcher_base, session_id)
        Console().print(f"[dim]to continue session run:[/dim] {resume_command}")
