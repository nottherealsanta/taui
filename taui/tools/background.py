"""Background process registry for long-running bash jobs.

The registry owns the async subprocess, drains its stdout into a bounded
ring buffer, and exposes incremental reads. The bash family of tools
(`bash` with `background: true`, `bash_status`, `bash_kill`) all talk
through this single object so a job started by one call is visible to the
others.

The buffer is bounded — once `max_buffer_bytes` is exceeded, the oldest
bytes are dropped (and the per-job cursor is decremented to match). The
intent is to bound memory, not to be a complete transcript; the agent
should be polling with `bash_status` to consume output as it lands.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class BackgroundProcess:
    bash_id: str
    command: str
    proc: asyncio.subprocess.Process
    started_at: float
    cwd: str
    buffer: bytearray = field(default_factory=bytearray)
    cursor: int = 0                # next byte to hand out via read()
    finished_at: float | None = None
    exit_code: int | None = None
    reader_task: asyncio.Task | None = None
    max_buffer_bytes: int = 1_000_000  # 1 MB
    _new_chunk: asyncio.Event = field(default_factory=asyncio.Event)


class BackgroundProcessRegistry:
    """Tracks background bash jobs for the lifetime of a session."""

    def __init__(self) -> None:
        self._procs: dict[str, BackgroundProcess] = {}

    async def start(
        self,
        *,
        command: str,
        cwd: str,
        env: dict[str, str],
        max_buffer_bytes: int = 1_000_000,
    ) -> BackgroundProcess:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        bash_id = f"bg_{uuid.uuid4().hex[:8]}"
        bp = BackgroundProcess(
            bash_id=bash_id,
            command=command,
            proc=proc,
            started_at=time.time(),
            cwd=cwd,
            max_buffer_bytes=max_buffer_bytes,
        )
        bp.reader_task = asyncio.create_task(self._drain(bp))
        self._procs[bash_id] = bp
        return bp

    async def _drain(self, bp: BackgroundProcess) -> None:
        assert bp.proc.stdout is not None
        try:
            while True:
                chunk = await bp.proc.stdout.read(4096)
                if not chunk:
                    break
                bp.buffer.extend(chunk)
                if len(bp.buffer) > bp.max_buffer_bytes:
                    overflow = len(bp.buffer) - bp.max_buffer_bytes
                    del bp.buffer[:overflow]
                    bp.cursor = max(0, bp.cursor - overflow)
                bp._new_chunk.set()
        finally:
            try:
                bp.exit_code = await bp.proc.wait()
            except Exception:
                bp.exit_code = bp.proc.returncode if bp.proc.returncode is not None else -1
            bp.finished_at = time.time()
            bp._new_chunk.set()  # unblock any waiters

    def get(self, bash_id: str) -> BackgroundProcess | None:
        return self._procs.get(bash_id)

    def list(self) -> list[BackgroundProcess]:
        return list(self._procs.values())

    def read(self, bash_id: str, *, max_bytes: int = 16_384) -> tuple[str, int]:
        """Read new output since the last call. Returns (text, new_cursor).

        Returns ("", cursor) when there is nothing new (caller should poll
        or wait via `wait_for_chunk`).
        """
        bp = self._procs.get(bash_id)
        if bp is None:
            return "", 0
        available = len(bp.buffer) - bp.cursor
        if available <= 0:
            bp._new_chunk.clear()
            return "", bp.cursor
        take = min(available, max_bytes)
        chunk = bytes(bp.buffer[bp.cursor : bp.cursor + take])
        bp.cursor += take
        if bp.cursor >= len(bp.buffer):
            bp._new_chunk.clear()
        return chunk.decode("utf-8", errors="replace"), bp.cursor

    async def wait_for_chunk(self, bash_id: str, *, timeout: float) -> bool:
        """Wait up to `timeout` seconds for a new chunk to arrive.

        Returns True if a new chunk landed (or the process exited), False on
        timeout / unknown id.
        """
        bp = self._procs.get(bash_id)
        if bp is None:
            return False
        try:
            await asyncio.wait_for(bp._new_chunk.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def kill(self, bash_id: str) -> bool:
        """Send SIGTERM then SIGKILL. Returns True if a signal was sent."""
        bp = self._procs.get(bash_id)
        if bp is None or bp.proc.returncode is not None:
            return False
        sent = False
        try:
            os.killpg(bp.proc.pid, signal.SIGTERM)
            sent = True
        except (ProcessLookupError, PermissionError, OSError):
            pass
        if sent:
            try:
                await asyncio.wait_for(bp.proc.wait(), timeout=2.0)
            except TimeoutError:
                try:
                    os.killpg(bp.proc.pid, signal.SIGKILL)
                    await bp.proc.wait()
                except (ProcessLookupError, OSError):
                    pass
        return sent

    async def shutdown(self) -> None:
        """Terminate every still-running process. Called at session teardown."""
        for bash_id in list(self._procs):
            bp = self._procs[bash_id]
            if bp.proc.returncode is None:
                await self.kill(bash_id)
            if bp.reader_task is not None:
                bp.reader_task.cancel()
