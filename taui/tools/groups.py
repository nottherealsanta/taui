"""Tool group resolution helpers.

Tool groups are a UI-level concept that bundle closely-related tools so
they can be presented together in pickers and toggle grids. Each tool may
declare a `group` attribute; tools without one form their own single-member
group keyed by their `name`.
"""

from __future__ import annotations

from typing import Any

from taui.tools.base import tool_group


def tool_to_group(tool: Any) -> str:
    """Return the group for a single tool instance."""
    return tool_group(tool)


def group_tools(tools: list[Any]) -> dict[str, list[str]]:
    """Bucket a flat list of tool instances by group name.

    Returns ``{group_name: [tool_name, ...]}`` with tool names sorted within
    each group.
    """
    out: dict[str, list[str]] = {}
    for tool in tools:
        g = tool_group(tool)
        out.setdefault(g, []).append(getattr(tool, "name", ""))
    for members in out.values():
        members.sort()
    return out


def resolve_groups_for_names(names: list[str]) -> dict[str, list[str]]:
    """Map tool names to canonical groups using the built-in registry.

    Used by self-edit UIs that need to know how to group tool names without
    holding a live registry. Tool names not known to the builtin registry
    form their own group keyed by themselves (presumed user extensions).
    """
    from taui.tools.builtins import register_builtins
    from taui.tools.registry import ToolRegistry

    reg = ToolRegistry()
    try:
        register_builtins(reg)
    except Exception:
        pass

    out: dict[str, list[str]] = {}
    for name in names:
        try:
            tool = reg.get(name)
            g = tool_group(tool)
        except Exception:
            g = name
        out.setdefault(g, []).append(name)
    for members in out.values():
        members.sort()
    return out
