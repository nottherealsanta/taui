"""
taui.extensions — extension discovery, loading, and management.

Extensions are Python files that register tools, commands, hooks, and
bundled prompt assets. Each extension is a ``.py`` file with a
``register(ctx)`` entry point.

Extension locations (later overrides earlier for same-named extensions):

  Global:
    ~/.taui/extensions/<name>.py

  Project:
    .taui/extensions/<name>.py

Each extension module must define::

    def register(ctx):
        ctx.tools.add(my_tool)
        ctx.commands.add(my_cmd)
        ctx.hooks.banner(lambda session: "hello")
        ctx.skills.add_path("skills/my-skill.md")

Legacy two- and three-argument signatures continue to work::

    def register(tools, commands, hooks): ...
    def register(tools, commands): ...

Extensions are isolated from core — a broken extension logs a warning
but does not crash the agent.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from taui.extensions.builtins import BUILTIN_EXTENSIONS

logger = logging.getLogger(__name__)


class SkillContribution:
    """Accumulates skill paths contributed by an extension during register()."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir
        self._paths: list[Path] = []

    def add_path(self, path: str | Path) -> None:
        """Register a skill file or SKILL.md directory.

        Relative paths are resolved against the extension's own directory.
        """
        p = Path(path)
        if not p.is_absolute() and self._base_dir is not None:
            p = self._base_dir / p
        self._paths.append(p)

    @property
    def paths(self) -> list[Path]:
        return list(self._paths)


@dataclass
class ExtensionContext:
    """Single argument passed to ``register(ctx)`` — holds all registration targets."""

    tools: Any                  # ToolRegistry | None
    commands: Any               # CommandRegistry | None
    hooks: Any                  # HookRegistry | None
    skills: SkillContribution = field(default_factory=SkillContribution)


@dataclass(slots=True)
class Extension:
    """A discovered extension."""

    name: str
    path: Path | None   # The .py file, or None for built-ins
    scope: str          # "global", "project", or "builtin"
    description: str = ""
    enabled: bool = True
    loaded: bool = False
    error: str | None = None
    skill_paths: list[Path] = field(default_factory=list)


class ExtensionRegistry:
    """Discovers and manages extensions.

    Scans global (~/.taui/extensions/) and project (.taui/extensions/)
    directories for .py files with a ``register()`` entry point.
    Project extensions override global ones with the same name.
    """

    GLOBAL_DIR = Path.home() / ".taui" / "extensions"
    PROJECT_DIR = ".taui/extensions"

    def __init__(self, working_dir: Path, *, include_builtins: bool = False) -> None:
        self._working_dir = working_dir
        self._include_builtins = include_builtins
        self._extensions: dict[str, Extension] = {}

    def discover(self) -> None:
        """Scan extension directories and populate the registry."""
        self._extensions.clear()

        if self._include_builtins:
            self._add_builtin_extensions()

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
            existing = self._extensions.get(name)
            if existing and existing.scope == "builtin":
                logger.warning(
                    "Ignoring %s extension '%s'; built-in extension names are reserved",
                    scope,
                    name,
                )
                continue
            self._extensions[name] = Extension(
                name=name,
                path=entry,
                scope=scope,
            )

    def _add_builtin_extensions(self) -> None:
        """Add Taui-shipped extension capabilities to the catalog."""
        for spec in BUILTIN_EXTENSIONS:
            self._extensions[spec.name] = Extension(
                name=spec.name,
                path=None,
                scope="builtin",
                description=spec.description,
                loaded=True,
            )

    def load_all(
        self, tools: Any = None, commands: Any = None, hooks: Any = None,
    ) -> list[str]:
        """Load all enabled extensions. Returns names of loaded extensions."""
        loaded: list[str] = []
        for ext in self._extensions.values():
            if not ext.enabled:
                continue
            if ext.scope == "builtin":
                ext.loaded = True
                ext.error = None
                loaded.append(ext.name)
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
                logger.warning("Extension '%s' has no register() function", ext.name)
                return False

            sig = inspect.signature(register_fn)
            params = list(sig.parameters)

            if len(params) == 1:
                # New-style: register(ctx)
                ctx = ExtensionContext(
                    tools=tools,
                    commands=commands,
                    hooks=hooks,
                    skills=SkillContribution(ext.path.parent if ext.path else None),
                )
                register_fn(ctx)
                ext.skill_paths = ctx.skills.paths
            elif len(params) >= 3 or "hooks" in sig.parameters:
                # Legacy three-argument: register(tools, commands, hooks)
                register_fn(tools=tools, commands=commands, hooks=hooks)
            else:
                # Legacy two-argument: register(tools, commands)
                register_fn(tools=tools, commands=commands)

            ext.loaded = True
            ext.error = None
            logger.info("Loaded extension: %s (%s)", ext.name, ext.scope)
            return True
        except Exception as e:
            ext.error = str(e)
            logger.warning("Failed to load extension '%s': %s", ext.name, e)
            return False

    def _import_extension(self, ext: Extension) -> ModuleType:
        """Import an extension module from its file path."""
        if ext.path is None:
            raise ImportError(f"Extension '{ext.name}' has no importable path")
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
