from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RunState:
    next_run_id: int = 1
    status: str = "idle"
    run_id: int | None = None
    spec_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "spec_ref": self.spec_ref,
        }

