"""
Agent naming — color-based name pool for root agents.

Root agents get auto-assigned color names (blue, red, green, ...).
Minions get auto-generated IDs like minion-<hex8>.
"""

from __future__ import annotations

import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

# Ordered pool of color names for root agents.
AGENT_COLORS: list[str] = [
    "blue",
    "red",
    "green",
    "amber",
    "violet",
    "cyan",
    "orange",
    "rose",
    "teal",
    "indigo",
]

# CSS hex colors matching each name (for frontend display).
AGENT_COLOR_HEX: dict[str, str] = {
    "blue": "#3b82f6",
    "red": "#ef4444",
    "green": "#22c55e",
    "amber": "#f59e0b",
    "violet": "#8b5cf6",
    "cyan": "#06b6d4",
    "orange": "#f97316",
    "rose": "#f43f5e",
    "teal": "#14b8a6",
    "indigo": "#6366f1",
}


class AgentNamePool:
    """Manages color-name allocation for root agents.

    Thread-safe for single-threaded async usage (no locks needed).
    """

    def __init__(self) -> None:
        self._in_use: set[str] = set()
        self._counter: int = 0  # fallback counter

    def allocate(self) -> str:
        """Return the next available color name, or a fallback."""
        for color in AGENT_COLORS:
            if color not in self._in_use:
                self._in_use.add(color)
                logger.debug("AgentNamePool allocated %r", color)
                return color
        # All colors in use — generate a numbered fallback
        self._counter += 1
        name = f"agent-{self._counter}"
        self._in_use.add(name)
        logger.debug("AgentNamePool allocated fallback %r", name)
        return name

    def release(self, name: str) -> None:
        """Return a name to the pool."""
        self._in_use.discard(name)
        logger.debug("AgentNamePool released %r", name)

    def is_color(self, name: str) -> bool:
        """Check if a name is one of the standard color names."""
        return name in AGENT_COLOR_HEX

    @property
    def active_names(self) -> frozenset[str]:
        return frozenset(self._in_use)


def generate_minion_id() -> str:
    """Generate a short unique ID for a minion agent."""
    return f"minion-{uuid4().hex[:8]}"
