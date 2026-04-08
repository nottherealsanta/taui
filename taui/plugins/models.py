"""Plugin data models — manifest, state, and contribution types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable


class PluginState(str, Enum):
    """Lifecycle state of a plugin."""

    DISCOVERED = "discovered"
    LOADING = "loading"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(slots=True)
class PluginManifest:
    """Declarative description of a plugin.

    Plugins expose a manifest that describes what they contribute to the
    system.  The manifest is used by the registry to wire up tools,
    hooks, prompt sections, and commands without the plugin needing to
    know about taui internals.
    """

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    # Contributions — what the plugin provides
    tool_factories: list[Callable[[], Any]] = field(default_factory=list)
    pre_hooks: list[Any] = field(default_factory=list)  # PreToolHook instances
    post_hooks: list[Any] = field(default_factory=list)  # PostToolHook instances
    prompt_sections: list[dict[str, Any]] = field(default_factory=list)
    # Each prompt_section: {"key": str, "content": str, "priority": int}
    commands: list[Any] = field(default_factory=list)

    # Lifecycle callbacks
    on_activate: Callable[[], None] | None = None
    on_deactivate: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Plugin manifest must have a non-empty name")


@runtime_checkable
class PluginEntryPoint(Protocol):
    """Protocol that plugin modules must implement.

    A plugin module must expose a ``create_manifest()`` function that
    returns a ``PluginManifest``.
    """

    def create_manifest(self) -> PluginManifest: ...


@dataclass(slots=True)
class PluginRecord:
    """Internal bookkeeping for a loaded plugin."""

    manifest: PluginManifest
    state: PluginState = PluginState.DISCOVERED
    error: str | None = None
    module: Any = None  # the loaded Python module

    @property
    def name(self) -> str:
        return self.manifest.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "description": self.manifest.description,
            "author": self.manifest.author,
            "state": self.state.value,
            "error": self.error,
            "tools": len(self.manifest.tool_factories),
            "hooks": len(self.manifest.pre_hooks) + len(self.manifest.post_hooks),
            "commands": len(self.manifest.commands),
        }
