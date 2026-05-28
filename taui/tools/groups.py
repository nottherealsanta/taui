"""Tool group resolution helpers.

Tool groups are a UI-level concept that bundle closely-related tools so
they can be presented together in pickers and toggle grids. Each tool may
declare a `group` attribute; tools without one form their own single-member
group keyed by their `name`.
"""

from __future__ import annotations

from pathlib import Path
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


def resolve_groups_for_names(
    names: list[str], working_dir: Path | None = None
) -> dict[str, list[str]]:
    """Map tool names to canonical groups using the built-in registry.

    Used by self-edit UIs that need to know how to group tool names without
    holding a live registry. When ``working_dir`` is provided, user
    extensions under ``~/.taui/extensions`` and ``<working_dir>/.taui/
    extensions`` are also loaded so extension-defined tool groups resolve
    correctly. Tool names still unknown form their own single-member group.
    """
    reg = _build_known_registry(working_dir)

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


def _build_known_registry(working_dir: Path | None) -> Any:
    """Fresh registry seeded with builtins + (optionally) user extensions."""
    reg, _ = _build_registry_with_attribution(working_dir)
    return reg


def _build_registry_with_attribution(
    working_dir: Path | None,
) -> tuple[Any, dict[str, list[str]]]:
    """Build a known registry and attribute each extension's tool names.

    Returns ``(registry, {extension_name: [tool_name, ...]})``. The
    attribution map is keyed by extension file stem (matching the names
    in ``~/.taui/extensions``) and lists the tools that file registered
    into the registry — used by self-edit UIs to expand a multi-tool
    extension file into per-tool rows.
    """
    from taui.tools.builtins import register_builtins
    from taui.tools.registry import ToolRegistry

    reg = ToolRegistry()
    try:
        register_builtins(reg)
    except Exception:
        pass
    attribution: dict[str, list[str]] = {}
    if working_dir is not None:
        try:
            from taui.extensions import ExtensionRegistry

            ext_reg = ExtensionRegistry(working_dir, include_builtins=False)
            ext_reg.discover()
            for ext in ext_reg.list_all():
                if ext.scope == "builtin" or not ext.enabled:
                    continue
                before = set(reg.names)
                ext_reg._load_one(ext, tools=reg)
                added = sorted(set(reg.names) - before)
                if added:
                    attribution[ext.name] = added
        except Exception:
            pass
    return reg, attribution
