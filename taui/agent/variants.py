"""Named agent variants — bundled configurations for different agent modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AgentVariant:
    """A named agent configuration bundle."""

    name: str
    description: str = ""
    model: str | None = None  # None = use session default
    system_prompt: str | None = None  # None = use session default
    tool_names: list[str] | None = None  # None = use all tools
    read_only: bool = False  # If True, exclude FILE_WRITE/SHELL/GIT tools
    max_turns: int | None = None  # None = use session default
    permission: dict[str, dict[str, str]] = field(default_factory=dict)


class AgentVariantRegistry:
    """Registry of available agent variants."""

    def __init__(self) -> None:
        self._variants: dict[str, AgentVariant] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register(AgentVariant(
            name="build",
            description="Default agent with full tool access.",
        ))
        self.register(AgentVariant(
            name="plan",
            description="Read-only agent for planning. Cannot modify files.",
            read_only=True,
            system_prompt=(
                "You are a planning assistant. You can read files and search "
                "the codebase, but you CANNOT modify any files. Your job is to "
                "analyze the codebase and create a detailed plan for the task. "
                "Write the plan as a structured response."
            ),
        ))

    def register(self, variant: AgentVariant) -> None:
        self._variants[variant.name] = variant

    def get(self, name: str) -> AgentVariant | None:
        return self._variants.get(name)

    def names(self) -> list[str]:
        return sorted(self._variants.keys())

    def all(self) -> list[AgentVariant]:
        return list(self._variants.values())

    def unregister(self, name: str) -> None:
        self._variants.pop(name, None)

    def discover_from_dir(self, agents_dir: Path) -> list[str]:
        """Load agent variants from .toml files in a directory.

        Returns names of loaded variants.
        """
        loaded = []
        if not agents_dir.is_dir():
            return loaded

        import tomllib

        for path in sorted(agents_dir.glob("*.toml")):
            try:
                with open(path, "rb") as f:
                    data: dict[str, Any] = tomllib.load(f)
                name = data.get("name", path.stem)
                variant = AgentVariant(
                    name=name,
                    description=data.get("description", ""),
                    model=data.get("model"),
                    system_prompt=data.get("system_prompt"),
                    tool_names=data.get("tools"),
                    read_only=data.get("read_only", False),
                    max_turns=data.get("max_turns"),
                    permission=data.get("permission", {}),
                )
                self.register(variant)
                loaded.append(name)
            except Exception:
                continue
        return loaded
