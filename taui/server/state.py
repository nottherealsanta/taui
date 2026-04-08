from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunProcess:
    run_id: int
    tangle_ref: str
    command: str
    workdir: str
    process: asyncio.subprocess.Process | None = None
    status: str = "running"
    exit_code: int | None = None
    output_buffer: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tangle_ref": self.tangle_ref,
            "spec_ref": self.tangle_ref,
            "command": self.command,
            "workdir": self.workdir,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(slots=True)
class RunState:
    next_run_id: int = 1
    status: str = "idle"
    run_id: int | None = None
    tangle_ref: str | None = None
    current_process: RunProcess | None = None
    notification_queue: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "tangle_ref": self.tangle_ref,
            "spec_ref": self.tangle_ref,
        }
