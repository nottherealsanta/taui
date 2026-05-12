"""Self-edit session helpers — re-exports from factory for backward compatibility."""

from taui.self_edit.factory import (
    build_scoped_tool_registry,
    build_self_edit_executor,
    build_self_edit_system_prompt,
    load_self_edit_system_prompt,
)

__all__ = [
    "build_scoped_tool_registry",
    "build_self_edit_executor",
    "build_self_edit_system_prompt",
    "load_self_edit_system_prompt",
]
