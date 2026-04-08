"""Plugin registry — discovers, loads, and manages plugin lifecycle."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from taui.plugins.models import (
    PluginManifest,
    PluginRecord,
    PluginState,
)

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Central registry for all plugins.

    Manages the full lifecycle: discover → load → activate → deactivate.
    Plugins contribute tools, hooks, prompt sections, and commands to the
    host system through their manifests.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginRecord] = {}

    # ── Registration ──────────────────────────────────────────────────

    def register(self, manifest: PluginManifest) -> PluginRecord:
        """Register a plugin from its manifest."""
        if manifest.name in self._plugins:
            raise ValueError(f"Plugin '{manifest.name}' is already registered")

        record = PluginRecord(manifest=manifest, state=PluginState.DISCOVERED)
        self._plugins[manifest.name] = record
        logger.info("Plugin registered: %s v%s", manifest.name, manifest.version)
        return record

    def register_from_module(self, module_path: str) -> PluginRecord:
        """Import a Python module and register its plugin manifest.

        The module must expose a ``create_manifest()`` function.
        """
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            logger.error("Failed to import plugin module %s: %s", module_path, exc)
            # Create an error record
            manifest = PluginManifest(
                name=module_path, description=f"Import failed: {exc}"
            )
            record = PluginRecord(
                manifest=manifest,
                state=PluginState.ERROR,
                error=str(exc),
                module=None,
            )
            self._plugins[module_path] = record
            return record

        create_fn = getattr(mod, "create_manifest", None)
        if create_fn is None:
            error = f"Module {module_path} does not expose create_manifest()"
            logger.error(error)
            manifest = PluginManifest(name=module_path, description=error)
            record = PluginRecord(
                manifest=manifest,
                state=PluginState.ERROR,
                error=error,
            )
            self._plugins[module_path] = record
            return record

        try:
            manifest = create_fn()
        except Exception as exc:
            logger.exception("Plugin %s create_manifest() failed", module_path)
            manifest = PluginManifest(name=module_path)
            record = PluginRecord(
                manifest=manifest,
                state=PluginState.ERROR,
                error=str(exc),
                module=mod,
            )
            self._plugins[module_path] = record
            return record

        record = PluginRecord(
            manifest=manifest,
            state=PluginState.DISCOVERED,
            module=mod,
        )
        self._plugins[manifest.name] = record
        logger.info(
            "Plugin discovered from module: %s v%s (%s)",
            manifest.name,
            manifest.version,
            module_path,
        )
        return record

    # ── Lifecycle ─────────────────────────────────────────────────────

    def activate(self, name: str) -> bool:
        """Activate a discovered plugin. Returns True on success."""
        record = self._plugins.get(name)
        if record is None:
            logger.warning("Cannot activate unknown plugin: %s", name)
            return False

        if record.state == PluginState.ACTIVE:
            return True

        if record.state == PluginState.ERROR:
            logger.warning("Cannot activate errored plugin: %s", name)
            return False

        record.state = PluginState.LOADING
        try:
            if record.manifest.on_activate is not None:
                record.manifest.on_activate()
            record.state = PluginState.ACTIVE
            logger.info("Plugin activated: %s", name)
            return True
        except Exception as exc:
            record.state = PluginState.ERROR
            record.error = str(exc)
            logger.exception("Plugin activation failed: %s", name)
            return False

    def deactivate(self, name: str) -> bool:
        """Deactivate an active plugin. Returns True on success."""
        record = self._plugins.get(name)
        if record is None:
            return False

        if record.state != PluginState.ACTIVE:
            return True

        try:
            if record.manifest.on_deactivate is not None:
                record.manifest.on_deactivate()
        except Exception:
            logger.exception("Plugin deactivation callback failed: %s", name)

        record.state = PluginState.DISABLED
        logger.info("Plugin deactivated: %s", name)
        return True

    def activate_all(self) -> dict[str, bool]:
        """Activate all discovered plugins. Returns {name: success}."""
        results: dict[str, bool] = {}
        for name, record in self._plugins.items():
            if record.state == PluginState.DISCOVERED:
                results[name] = self.activate(name)
        return results

    # ── Queries ────────────────────────────────────────────────────────

    def get(self, name: str) -> PluginRecord | None:
        return self._plugins.get(name)

    def list_all(self) -> list[PluginRecord]:
        return list(self._plugins.values())

    def list_active(self) -> list[PluginRecord]:
        return [r for r in self._plugins.values() if r.state == PluginState.ACTIVE]

    @property
    def count(self) -> int:
        return len(self._plugins)

    # ── Contribution collection ───────────────────────────────────────

    def collect_tool_factories(self) -> list[Any]:
        """Collect all tool factories from active plugins."""
        factories: list[Any] = []
        for record in self.list_active():
            factories.extend(record.manifest.tool_factories)
        return factories

    def collect_pre_hooks(self) -> list[Any]:
        """Collect all pre-tool-use hooks from active plugins."""
        hooks: list[Any] = []
        for record in self.list_active():
            hooks.extend(record.manifest.pre_hooks)
        return hooks

    def collect_post_hooks(self) -> list[Any]:
        """Collect all post-tool-use hooks from active plugins."""
        hooks: list[Any] = []
        for record in self.list_active():
            hooks.extend(record.manifest.post_hooks)
        return hooks

    def collect_prompt_sections(self) -> list[dict[str, Any]]:
        """Collect all prompt sections from active plugins."""
        sections: list[dict[str, Any]] = []
        for record in self.list_active():
            sections.extend(record.manifest.prompt_sections)
        return sections

    def collect_commands(self) -> list[Any]:
        """Collect all commands from active plugins."""
        commands: list[Any] = []
        for record in self.list_active():
            commands.extend(record.manifest.commands)
        return commands

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "active": len(self.list_active()),
            "plugins": [r.to_dict() for r in self._plugins.values()],
        }
