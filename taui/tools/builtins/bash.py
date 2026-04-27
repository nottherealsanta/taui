"""Bash tool — sandboxed shell command execution."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.common import truncate

_MAX_OUTPUT_BYTES = 50_000  # 50 KB output cap
_MAX_OUTPUT_LINES = 2000

# Env vars safe to pass through
_ENV_ALLOWLIST = frozenset({
    "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "PATH", "SHELL", "TERM", "TMPDIR",
    "EDITOR", "VISUAL", "PAGER",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
})


def _filtered_env() -> dict[str, str]:
    """Return a sanitized env dict — only allowlisted vars."""
    return {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}


@dataclass
class BashTool:
    """Execute a shell command."""

    name: str = "bash"
    description: str = (
        "Execute a bash command and return its output. "
        "Commands run in the working directory with a filtered environment."
    )
    category: ToolCategory = ToolCategory.SHELL
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `bash` for running shell commands. Prefer other tools when "
        "a dedicated tool exists (e.g. `read` over `cat`, `grep` over `grep`). "
        "Always pass a reasonable timeout for long commands."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default: 60.",
                    },
                },
                "required": ["command"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command", "")
        if not command.strip():
            return ToolResult.fail("Empty command")

        timeout = min(arguments.get("timeout", 60), 300)  # Cap at 5 min
        cwd = str(self.working_dir)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=_filtered_env(),
                start_new_session=True,  # Own process group for clean kill
            )
        except OSError as e:
            return ToolResult.fail(f"Failed to start process: {e}")

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the process group
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                await asyncio.sleep(1)
                if proc.returncode is None:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            return ToolResult.fail(
                f"Command timed out after {timeout}s: {command}",
                command=command,
                timeout=timeout,
            )

        output = stdout.decode("utf-8", errors="replace") if stdout else ""

        # Truncate large output using shared utility
        output, was_truncated = truncate(
            output, max_lines=_MAX_OUTPUT_LINES, max_bytes=_MAX_OUTPUT_BYTES
        )

        exit_code = proc.returncode or 0
        meta = dict(exit_code=exit_code, command=command, truncated=was_truncated)

        if exit_code != 0:
            return ToolResult(
                content=f"Exit code: {exit_code}\n{output}",
                error=True,
                metadata=meta,
            )

        return ToolResult.ok(output if output else "(no output)", **meta)
