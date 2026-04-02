from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import Tool, ToolCategory


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def register_or_replace(self, tool: Tool) -> None:
        """Register a tool, replacing any existing tool with the same name."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' is not registered.")
        del self._tools[name]

    def unregister_by_origin(self, origin_prefix: str) -> int:
        """Remove all tools whose origin starts with *origin_prefix*."""
        to_remove = [
            n for n, t in self._tools.items() if t.origin.startswith(origin_prefix)
        ]
        for name in to_remove:
            del self._tools[name]
        return len(to_remove)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool '{name}'.") from exc

    def list_schemas(
        self,
        *,
        categories: set[ToolCategory] | None = None,
        exclude_categories: set[ToolCategory] | None = None,
    ) -> list[dict[str, object]]:
        schemas: list[dict[str, object]] = []
        for tool in self._tools.values():
            cat = getattr(tool, "category", None)
            if categories and cat not in categories:
                continue
            if exclude_categories and cat in exclude_categories:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema,
                    },
                }
            )
        return schemas

    def tools_for_agent(
        self,
        *,
        categories: set[ToolCategory] | None = None,
        exclude_categories: set[ToolCategory] | None = None,
    ) -> list[Tool]:
        """Return tools filtered by category."""
        tools: list[Tool] = []
        for tool in self._tools.values():
            cat = getattr(tool, "category", None)
            if categories and cat not in categories:
                continue
            if exclude_categories and cat in exclude_categories:
                continue
            tools.append(tool)
        return tools

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def names_by_origin(self, prefix: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                name
                for name, tool in self._tools.items()
                if tool.origin.startswith(prefix)
            )
        )

    def names_by_category(self, category: ToolCategory) -> tuple[str, ...]:
        return tuple(
            sorted(
                name
                for name, tool in self._tools.items()
                if getattr(tool, "category", None) == category
            )
        )

    def register_skills_as_tools(self, skill_registry: Any) -> int:
        """Bridge skills into the tool registry.

        Skills that define a ``schema`` are registered as standalone tools
        (claw-code pattern: skill-to-tool bridge).  Skills without schemas
        remain accessible only through the ``skill`` tool's ``invoke``
        operation.

        Returns the number of skills registered as tools.
        """
        from taui.tools.skill_bridge import SkillBridgeTool

        count = 0
        for skill in skill_registry.list_skills():
            if skill.schema is not None:
                tool_name = f"skill_{skill.name}"
                if tool_name in self._tools:
                    continue
                bridge = SkillBridgeTool(skill=skill)
                self._tools[tool_name] = bridge  # type: ignore[assignment]
                count += 1
        return count
