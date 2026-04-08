"""Agent definitions — named agent types with pre-configured tool sets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory


@dataclass(slots=True)
class AgentDefinition:
    """Defines a named agent mode with allowed/denied tool categories."""

    name: str
    description: str
    system_prompt_prefix: str = ""
    allowed_categories: set[ToolCategory] | None = None  # None = all
    denied_categories: set[ToolCategory] | None = None
    max_turns: int = 50

    def accepts_category(self, cat: ToolCategory) -> bool:
        if self.denied_categories and cat in self.denied_categories:
            return False
        if self.allowed_categories is not None:
            return cat in self.allowed_categories
        return True


# Pre-defined agent types

EXPLORER = AgentDefinition(
    name="explorer",
    description="Read-only exploration — searches, reads files, and analyzes code.",
    system_prompt_prefix=(
        "You are a read-only exploration agent. You may search, read files, "
        "and analyze code, but you must NOT modify any files."
    ),
    allowed_categories={
        ToolCategory.FILE_READ,
        ToolCategory.SEARCH,
        ToolCategory.LSP,
        ToolCategory.GIT,
        ToolCategory.PLAN,
        ToolCategory.SPEC,
    },
    max_turns=30,
)

PLANNER = AgentDefinition(
    name="planner",
    description="Creates plans and specs, reads code, but no file writes.",
    system_prompt_prefix=(
        "You are a planning agent. Analyze the codebase, create plans and specs. "
        "Do not modify source files."
    ),
    allowed_categories={
        ToolCategory.FILE_READ,
        ToolCategory.SEARCH,
        ToolCategory.LSP,
        ToolCategory.GIT,
        ToolCategory.PLAN,
        ToolCategory.SPEC,
        ToolCategory.SKILL,
    },
    max_turns=40,
)

BUILDER = AgentDefinition(
    name="builder",
    description="Full access — reads, writes, runs commands, modifies specs.",
    system_prompt_prefix=(
        "You are a builder agent with full tool access. Implement features, fix bugs, "
        "and refactor code as needed."
    ),
    # All categories allowed
    max_turns=80,
)

GENERAL = AgentDefinition(
    name="general",
    description="Default agent with balanced permissions.",
    max_turns=50,
)


# Registry of built-in agent defs
AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    d.name: d for d in [EXPLORER, PLANNER, BUILDER, GENERAL]
}


def get_agent_definition(name: str) -> AgentDefinition:
    """Look up a named agent definition."""
    if name not in AGENT_DEFINITIONS:
        available = ", ".join(sorted(AGENT_DEFINITIONS))
        raise ValueError(
            f"Unknown agent type '{name}'. Available: {available}"
        )
    return AGENT_DEFINITIONS[name]
