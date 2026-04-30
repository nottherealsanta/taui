"""
taui.extensions — extension discovery, loading, and management.

Extensions are Python files that register additional tools, commands,
hooks, or prompt fragments. They follow a simple convention: each extension
is a ``.py`` file with a ``register()`` entry point.

Extension locations (later overrides earlier for same-named extensions):

  Global:
    ~/.taui/extensions/<name>.py

  Project:
    .taui/extensions/<name>.py

Each extension module must define::

    def register(tools, commands, hooks):
        '''Register extension components.

        Args:
            tools: ToolRegistry — call tools.register(my_tool)
            commands: CommandRegistry — call commands.register(my_cmd)
            hooks: HookRegistry — call hooks.prompt(fn), hooks.status(fn), etc.
        '''

The ``hooks`` parameter was added later; extensions that only accept
``(tools, commands)`` continue to work unchanged.

Extensions are isolated from core — a broken extension logs a warning
but does not crash the agent.  Use ``--no-extensions`` to skip loading.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Extension:
    """A discovered extension."""

    name: str
    path: Path          # The .py file
    scope: str          # "global" or "project"
    enabled: bool = True
    loaded: bool = False
    error: str | None = None


class ExtensionRegistry:
    """Discovers and manages extensions.

    Scans global (~/.taui/extensions/) and project (.taui/extensions/)
    directories for .py files with a ``register()`` entry point.
    Project extensions override global ones with the same name.
    """

    GLOBAL_DIR = Path.home() / ".taui" / "extensions"
    PROJECT_DIR = ".taui/extensions"

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._extensions: dict[str, Extension] = {}

    def discover(self) -> None:
        """Scan extension directories and populate the registry."""
        self._extensions.clear()

        # Global extensions
        self._scan_dir(self.GLOBAL_DIR, scope="global")

        # Project extensions (override global)
        project_dir = self._working_dir / self.PROJECT_DIR
        self._scan_dir(project_dir, scope="project")

    def _scan_dir(self, base: Path, scope: str) -> None:
        """Scan a directory for extension .py files."""
        if not base.is_dir():
            return
        for entry in sorted(base.iterdir()):
            if not entry.is_file() or entry.suffix != ".py":
                continue
            if entry.name.startswith("_"):
                continue
            name = entry.stem
            self._extensions[name] = Extension(
                name=name,
                path=entry,
                scope=scope,
            )

    def load_all(
        self, tools: Any = None, commands: Any = None, hooks: Any = None,
    ) -> list[str]:
        """Load all enabled extensions. Returns names of loaded extensions."""
        loaded: list[str] = []
        for ext in self._extensions.values():
            if not ext.enabled:
                continue
            if self._load_one(ext, tools, commands, hooks):
                loaded.append(ext.name)
        return loaded

    def _load_one(
        self,
        ext: Extension,
        tools: Any = None,
        commands: Any = None,
        hooks: Any = None,
    ) -> bool:
        """Load a single extension. Returns True on success."""
        if ext.loaded:
            return True
        try:
            module = self._import_extension(ext)
            register_fn = getattr(module, "register", None)
            if register_fn is None:
                ext.error = "Missing register() function"
                logger.warning(
                    "Extension '%s' has no register() function", ext.name
                )
                return False
            # Try new signature (tools, commands, hooks) first;
            # fall back to legacy (tools, commands) for compat.
            import inspect
            sig = inspect.signature(register_fn)
            if len(sig.parameters) >= 3 or "hooks" in sig.parameters:
                register_fn(tools=tools, commands=commands, hooks=hooks)
            else:
                register_fn(tools=tools, commands=commands)
            ext.loaded = True
            ext.error = None
            logger.info("Loaded extension: %s (%s)", ext.name, ext.scope)
            return True
        except Exception as e:
            ext.error = str(e)
            logger.warning(
                "Failed to load extension '%s': %s", ext.name, e
            )
            return False

    def _import_extension(self, ext: Extension) -> ModuleType:
        """Import an extension module from its file path."""
        module_name = f"taui_ext_{ext.name}"
        spec = importlib.util.spec_from_file_location(module_name, ext.path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {ext.path}")
        module = importlib.util.module_from_spec(spec)
        # Don't pollute sys.modules permanently — keep it scoped
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    @property
    def names(self) -> list[str]:
        return sorted(self._extensions)

    def get(self, name: str) -> Extension | None:
        return self._extensions.get(name)

    def list_all(self) -> list[Extension]:
        return [self._extensions[n] for n in self.names]

    def loaded_extensions(self) -> list[Extension]:
        return [e for e in self._extensions.values() if e.loaded]

    def unload_all(self) -> None:
        """Mark all extensions as unloaded and remove their modules from sys.modules."""
        for ext in self._extensions.values():
            module_name = f"taui_ext_{ext.name}"
            sys.modules.pop(module_name, None)
            ext.loaded = False
            ext.error = None
