"""Tool registry — named collection of tools with lookup and schema export."""

from __future__ import annotations

from typing import Any

from taui.tools.base import Tool, ToolCategory


class ToolRegistry:
    """Registry of available tools.

    Supports registration, lookup, filtering by category,
    and exporting schemas in OpenAI function-calling format.

    Usage::

        registry = ToolRegistry()
        registry.register(my_tool)
        tool = registry.get("my_tool")
        schemas = registry.schemas()
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises if a tool with the same name exists."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def register_or_replace(self, tool: Tool) -> None:
        """Register a tool, replacing any existing tool with the same name."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> Tool:
        """Remove and return a tool by name. Raises if not found."""
        try:
            return self._tools.pop(name)
        except KeyError:
            raise ValueError(f"Tool not registered: {name!r}") from None

    def get(self, name: str) -> Tool:
        """Look up a tool by name. Raises if not found."""
        try:
            return self._tools[name]
        except KeyError:
            raise ValueError(f"Unknown tool: {name!r}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def by_category(self, category: ToolCategory) -> list[Tool]:
        """Return all tools in a category."""
        return [t for t in self._tools.values() if t.category == category]

    def schemas(
        self,
        *,
        include: set[ToolCategory] | None = None,
        exclude: set[ToolCategory] | None = None,
    ) -> list[dict[str, Any]]:
        """Export tool schemas in OpenAI function-calling format.

        Optionally filter by category inclusion/exclusion.
        """
        result: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if include and tool.category not in include:
                continue
            if exclude and tool.category in exclude:
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema,
                },
            })
        return result

    def subset(self, names: list[str]) -> ToolRegistry:
        """Create a new registry containing only the named tools.

        Useful for scoping a sub-agent's available tools.
        """
        sub = ToolRegistry()
        for name in names:
            sub._tools[name] = self.get(name)
        return sub

    def guidelines(self) -> str:
        """Collect guidelines from all tools that have them.

        Returns a formatted string suitable for appending to the system prompt.
        """
        sections: list[str] = []
        for tool in self._tools.values():
            guide = getattr(tool, "guidelines", None)
            if guide:
                sections.append(f"- **{tool.name}**: {guide}")
        if not sections:
            return ""
        return "## Tool Guidelines\n\n" + "\n".join(sections)

    def output_schema(self, name: str) -> dict[str, Any] | None:
        """Get a tool's output schema, if defined."""
        tool = self.get(name)
        return getattr(tool, "output_schema", None)
