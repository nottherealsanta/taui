from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import asyncio
import os
import signal

from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error


@dataclass(slots=True)
class BashTool:
    name: str = "bash"
    description: str = "Execute a shell command"
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                    "workdir": {"type": "string"},
                },
                "required": ["command"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        command = arguments.get("command")
        timeout = arguments.get("timeout")
        workdir = arguments.get("workdir")

        if not isinstance(command, str) or not command.strip():
            return normalize_tool_error(
                "Invalid bash arguments: 'command' must be a non-empty string."
            )
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            return normalize_tool_error(
                "Invalid bash arguments: 'timeout' must be a positive integer."
            )
        if workdir is not None and not isinstance(workdir, str):
            return normalize_tool_error(
                "Invalid bash arguments: 'workdir' must be a string."
            )

        cwd = _resolve_workdir(context, workdir)
        if isinstance(cwd, ToolResult):
            return cwd

        bash_settings = context.policy.bash
        timeout_sec = timeout or bash_settings.default_timeout_sec
        env = _filtered_env(bash_settings.env_allowlist)

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_sec
            )
        except TimeoutError:
            await _terminate_process_group(process)
            return normalize_tool_error(
                f"Command timed out after {timeout_sec} seconds.",
                metadata={"timeout": True, "workdir": str(cwd), "command": command},
            )

        output = _format_output(stdout, stderr)
        truncated_output, truncated = _truncate(output, bash_settings.max_output_bytes)
        return ToolResult(
            content=truncated_output,
            error=process.returncode != 0,
            metadata={
                "exit_code": process.returncode,
                "workdir": str(cwd),
                "truncated": truncated,
            },
        )


def _resolve_workdir(context: ToolContext, workdir: str | None) -> Path | ToolResult:
    target = Path(workdir) if workdir else context.working_dir
    if not target.is_absolute():
        target = context.working_dir / target
    resolved = target.resolve()
    workspace = context.working_dir.resolve()
    if context.policy.bash.restrict_workdir_to_workspace:
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return normalize_tool_error(
                f"Bash workdir '{resolved}' is outside workspace '{workspace}'."
            )
    if not resolved.exists() or not resolved.is_dir():
        return normalize_tool_error(f"Bash workdir does not exist: {resolved}")
    return resolved


def _filtered_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in allowlist:
        value = os.getenv(key)
        if value is not None:
            env[key] = value
    return env


def _format_output(stdout: bytes, stderr: bytes) -> str:
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if out and err:
        return f"[stdout]\n{out}\n[stderr]\n{err}"
    if out:
        return out
    if err:
        return f"[stderr]\n{err}"
    return ""


def _truncate(text: str, max_output_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_output_bytes:
        return text, False
    clipped = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
    return f"{clipped}\n\n[output truncated]", True


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()
