from __future__ import annotations

from dataclasses import dataclass, field

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
