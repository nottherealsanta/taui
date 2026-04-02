"""Plugin system — inspired by claw-code's plugin lifecycle.

Plugins extend taui with custom tools, hooks, prompt sections, and
commands.  Each plugin is a Python package that exposes a manifest
(``PluginManifest``) and optional lifecycle callbacks.

The plugin registry discovers, loads, and manages the lifecycle of all
installed plugins.
"""

from taui.plugins.models import PluginManifest, PluginState
from taui.plugins.registry import PluginRegistry

__all__ = ["PluginManifest", "PluginRegistry", "PluginState"]
