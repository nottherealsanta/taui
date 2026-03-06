from __future__ import annotations

from dataclasses import dataclass, field

from taui.tools.base import Tool


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' is not registered.")
        del self._tools[name]

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool '{name}'.") from exc

    def list_schemas(self) -> list[dict[str, object]]:
        schemas: list[dict[str, object]] = []
        for tool in self._tools.values():
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
