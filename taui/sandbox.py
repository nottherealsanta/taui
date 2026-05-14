"""Sandbox policy for tool execution.

Defines which filesystem paths and network access are permitted.
Tools check the policy before executing. The actual enforcement
(bwrap, sandbox-exec) is platform-specific and opt-in.

Usage in config::

    [taui.sandbox]
    enabled = false
    writable_dirs = [".", "/tmp"]
    readable_dirs = ["/"]
    network = false
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SandboxPolicy:
    """Declarative sandbox policy.

    Tools can query this to check if an operation is permitted
    before attempting it. When `enabled` is False, everything
    is allowed.
    """

    enabled: bool = False
    writable_dirs: list[str] = field(default_factory=lambda: [".", "/tmp"])
    readable_dirs: list[str] = field(default_factory=lambda: ["/"])
    network: bool = True

    def is_path_writable(self, path: Path, working_dir: Path) -> bool:
        """Check if a path is writable under this policy."""
        if not self.enabled:
            return True
        resolved = path.resolve()
        for d in self.writable_dirs:
            base = Path(d)
            if not base.is_absolute():
                base = working_dir / base
            try:
                resolved.relative_to(base.resolve())
                return True
            except ValueError:
                continue
        return False

    def is_path_readable(self, path: Path, working_dir: Path) -> bool:
        """Check if a path is readable under this policy."""
        if not self.enabled:
            return True
        resolved = path.resolve()
        for d in self.readable_dirs + self.writable_dirs:
            base = Path(d)
            if not base.is_absolute():
                base = working_dir / base
            try:
                resolved.relative_to(base.resolve())
                return True
            except ValueError:
                continue
        return False

    def is_network_allowed(self) -> bool:
        """Check if network access is permitted."""
        if not self.enabled:
            return True
        return self.network

    @classmethod
    def from_config(cls, cfg: dict) -> SandboxPolicy:
        """Create from a config dict (e.g. [taui.sandbox])."""
        return cls(
            enabled=cfg.get("enabled", False),
            writable_dirs=cfg.get("writable_dirs", [".", "/tmp"]),
            readable_dirs=cfg.get("readable_dirs", ["/"]),
            network=cfg.get("network", True),
        )
