"""Bash tool — sandboxed shell command execution.

Foreground mode captures and returns output synchronously. Background mode
spawns the process via the BackgroundProcessRegistry and returns a `bash_id`
that companion tools (`bash_status`, `bash_kill`) use to stream output or
terminate the job. Foreground truncation emits a structured envelope so the
agent knows when it has only partial output.
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.background import BackgroundProcessRegistry
from taui.tools.base import ToolCategory, ToolResult, emit_tool_output_delta
from taui.tools.builtins.common import TruncationEnvelope

_MAX_OUTPUT_BYTES = 50_000  # 50 KB output cap (foreground)
_MAX_OUTPUT_LINES = 2000

# Env vars safe to pass through
_ENV_ALLOWLIST = frozenset({
    "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "PATH", "SHELL", "TERM", "TMPDIR",
    "EDITOR", "VISUAL", "PAGER",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
})


async def _drain_stdout(
    proc: asyncio.subprocess.Process, raw: bytearray
) -> None:
    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        raw.extend(chunk)
        try:
            await emit_tool_output_delta(chunk.decode("utf-8", errors="replace"))
        except Exception:
            pass


def _filtered_env() -> dict[str, str]:
    """Return a sanitized env dict — only allowlisted vars."""
    return {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}


def _truncate_bytes(
    raw: bytes, *, max_bytes: int, max_lines: int
) -> tuple[str, bool, int]:
    """Cut raw bytes to fit byte + line caps. Returns (text, truncated, kept_bytes).

    Splits on the last newline within the cap to avoid producing a half-line.
    """
    if len(raw) <= max_bytes:
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        if len(lines) <= max_lines:
            return text, False, len(raw)
        kept = "".join(lines[:max_lines])
        return kept, True, len(kept.encode("utf-8", errors="replace"))

    head = raw[:max_bytes]
    nl = head.rfind(b"\n")
    if nl > 0:
        head = head[: nl + 1]
    text = head.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        text = "".join(lines[:max_lines])
    return text, True, len(text.encode("utf-8", errors="replace"))


@dataclass
class BashTool:
    """Execute a shell command — foreground or background."""

    name: str = "bash"
    description: str = (
        "Execute a bash command and return its output. "
        "Commands run in the working directory with a filtered environment. "
        "Set `background: true` for long-running jobs (servers, watchers, "
        "test suites, builds) — returns a bash_id you can poll with "
        "`bash_status` and terminate with `bash_kill`."
    )
    category: ToolCategory = ToolCategory.SHELL
    group: str = "bash"
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `bash` for running shell commands. Prefer other tools when "
        "a dedicated tool exists (e.g. `read` over `cat`, `grep` over `grep`). "
        "Always pass a reasonable timeout for long commands. For commands that "
        "won't complete in seconds, prefer `background: true`."
    )
    _truncation_store: Any = field(default=None, repr=False)
    _bg_registry: BackgroundProcessRegistry | None = None
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
                        "description": "Timeout in seconds (foreground only). Default: 60.",
                    },
                    "background": {
                        "type": "boolean",
                        "description": (
                            "Run in the background. Returns a bash_id immediately "
                            "(after capturing the first stdout chunk). Poll with "
                            "`bash_status` and terminate with `bash_kill`."
                        ),
                    },
                    "initial_wait": {
                        "type": "number",
                        "description": (
                            "When `background: true`, seconds to wait for the "
                            "first chunk before returning. Default: 1.0."
                        ),
                    },
                },
                "required": ["command"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command", "")
        if not command.strip():
            return ToolResult.fail("Empty command")

        if arguments.get("background"):
            return await self._execute_background(command, arguments)
        return await self._execute_foreground(command, arguments)

    async def _execute_foreground(
        self, command: str, arguments: dict[str, Any]
    ) -> ToolResult:
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

        raw_buffer = bytearray()
        reader_task = asyncio.create_task(_drain_stdout(proc, raw_buffer))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            # Kill the process group
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                if proc.returncode is None:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            except TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
                except (ProcessLookupError, OSError):
                    pass
        finally:
            try:
                await asyncio.wait_for(reader_task, timeout=1.0)
            except TimeoutError:
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass
            except Exception:
                pass

        raw = bytes(raw_buffer)
        total_bytes = len(raw)
        text, was_truncated, kept_bytes = _truncate_bytes(
            raw, max_bytes=_MAX_OUTPUT_BYTES, max_lines=_MAX_OUTPUT_LINES
        )

        if timed_out:
            message = (
                f"Command timed out after {timeout}s: {command}. "
                "Re-run with `background: true` for long-running jobs."
            )
            if text:
                message += f"\n\n--- partial output ---\n{text}"
            return ToolResult.fail(
                message,
                command=command,
                timeout=timeout,
                timed_out=True,
                truncated=was_truncated,
            )

        exit_code = proc.returncode or 0
        meta: dict[str, Any] = {
            "exit_code": exit_code,
            "command": command,
            "truncated": was_truncated,
        }

        if was_truncated:
            handle: str | None = None
            if self._truncation_store is not None:
                handle = self._truncation_store.store(
                    raw.decode("utf-8", errors="replace"), tool_name="bash"
                )
            envelope = TruncationEnvelope(
                truncated_at=kept_bytes,
                unit="bytes",
                total_hint=total_bytes,
                peek_handle=handle,
                next_hint=(
                    "rerun with a narrower command (e.g. pipe through head/tail/grep), "
                    "or use `background: true` and stream via bash_status"
                ),
            )
            text += envelope.format_footer()
            meta.update(envelope.to_metadata())

        if exit_code != 0:
            return ToolResult(
                content=f"Exit code: {exit_code}\n{text}",
                error=True,
                metadata=meta,
            )

        return ToolResult.ok(text if text else "(no output)", **meta)

    async def _execute_background(
        self, command: str, arguments: dict[str, Any]
    ) -> ToolResult:
        if self._bg_registry is None:
            return ToolResult.fail(
                "Background mode unavailable — no background process registry "
                "is wired into this session."
            )
        initial_wait = float(arguments.get("initial_wait", 1.0))
        initial_wait = max(0.0, min(initial_wait, 10.0))
        cwd = str(self.working_dir)

        try:
            bp = await self._bg_registry.start(
                command=command, cwd=cwd, env=_filtered_env()
            )
        except OSError as e:
            return ToolResult.fail(f"Failed to start process: {e}")

        # Give the process a moment to produce its first chunk so the agent
        # gets immediate feedback instead of a near-empty acknowledgment.
        if initial_wait > 0:
            try:
                await asyncio.wait_for(bp.proc.wait(), timeout=initial_wait)
            except TimeoutError:
                pass

        chunk, _cursor = self._bg_registry.read(bp.bash_id, max_bytes=8 * 1024)
        running = bp.exit_code is None
        status = "running" if running else f"exited (code {bp.exit_code})"

        header = (
            f"Started background bash: bash_id={bp.bash_id}\n"
            f"  command: {command}\n"
            f"  status:  {status}\n"
        )
        body = (
            "\n--- initial output ---\n" + chunk
            if chunk
            else "\n(no output yet — use bash_status to fetch new chunks)"
        )
        return ToolResult.ok(
            header + body,
            bash_id=bp.bash_id,
            running=running,
            exit_code=bp.exit_code,
            command=command,
        )


# ── BashStatusTool ────────────────────────────────────────────────────────────


@dataclass
class BashStatusTool:
    """Poll a background bash job for new output and lifecycle state."""

    name: str = "bash_status"
    description: str = (
        "Fetch new stdout/stderr from a background bash job and report whether "
        "it is still running. Each call returns only the bytes produced since "
        "the previous call (incremental stream)."
    )
    category: ToolCategory = ToolCategory.SHELL
    group: str = "bash"
    guidelines: str = (
        "Use after `bash` with `background: true` to stream incremental output. "
        "Call repeatedly until `running: false` to drain a job to completion."
    )
    _bg_registry: BackgroundProcessRegistry | None = None
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "bash_id": {
                        "type": "string",
                        "description": "ID returned by a background `bash` call.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": (
                            "Maximum bytes of new output to return. Default 16384."
                        ),
                    },
                    "wait": {
                        "type": "number",
                        "description": (
                            "If no output is buffered, wait up to this many "
                            "seconds for the first new chunk. Default 0 (return "
                            "whatever is already buffered)."
                        ),
                    },
                },
                "required": ["bash_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._bg_registry is None:
            return ToolResult.fail("Background process registry unavailable.")
        bash_id = arguments.get("bash_id", "")
        if not bash_id:
            return ToolResult.fail("Missing bash_id.")
        bp = self._bg_registry.get(bash_id)
        if bp is None:
            return ToolResult.fail(f"Unknown bash_id: {bash_id!r}")

        max_bytes = int(arguments.get("max_bytes", 16384))
        wait = float(arguments.get("wait", 0.0))
        wait = max(0.0, min(wait, 30.0))

        chunk, _cursor = self._bg_registry.read(bash_id, max_bytes=max_bytes)
        if not chunk and wait > 0 and bp.exit_code is None:
            await self._bg_registry.wait_for_chunk(bash_id, timeout=wait)
            chunk, _cursor = self._bg_registry.read(bash_id, max_bytes=max_bytes)

        running = bp.exit_code is None
        status = "running" if running else f"exited (code {bp.exit_code})"
        header = (
            f"bash_id={bash_id}  status={status}  "
            f"buffered_bytes={len(bp.buffer)}  cursor={bp.cursor}"
        )
        body = "\n" + chunk if chunk else "\n(no new output)"
        return ToolResult.ok(
            header + body,
            bash_id=bash_id,
            running=running,
            exit_code=bp.exit_code,
            new_bytes=len(chunk.encode("utf-8", errors="replace")),
        )


# ── BashKillTool ──────────────────────────────────────────────────────────────


@dataclass
class BashKillTool:
    """Terminate a background bash job."""

    name: str = "bash_kill"
    description: str = (
        "Terminate a background bash job. Sends SIGTERM, then SIGKILL after "
        "a short grace period if the process is still alive."
    )
    category: ToolCategory = ToolCategory.SHELL
    group: str = "bash"
    guidelines: str = (
        "Use to clean up a background job started by `bash` with `background: "
        "true` — particularly when it's a server/watcher you no longer need."
    )
    _bg_registry: BackgroundProcessRegistry | None = None
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "bash_id": {
                        "type": "string",
                        "description": "ID of the background job to terminate.",
                    },
                },
                "required": ["bash_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._bg_registry is None:
            return ToolResult.fail("Background process registry unavailable.")
        bash_id = arguments.get("bash_id", "")
        if not bash_id:
            return ToolResult.fail("Missing bash_id.")
        bp = self._bg_registry.get(bash_id)
        if bp is None:
            return ToolResult.fail(f"Unknown bash_id: {bash_id!r}")

        if bp.exit_code is not None:
            return ToolResult.ok(
                f"bash_id={bash_id} already exited with code {bp.exit_code}.",
                bash_id=bash_id,
                already_exited=True,
                exit_code=bp.exit_code,
            )

        killed = await self._bg_registry.kill(bash_id)
        return ToolResult.ok(
            f"bash_id={bash_id} {'terminated' if killed else 'not running'} "
            f"(exit code {bp.exit_code}).",
            bash_id=bash_id,
            killed=killed,
            exit_code=bp.exit_code,
        )
