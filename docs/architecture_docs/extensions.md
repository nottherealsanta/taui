# Extension System

Extensions are Python files that register additional tools, commands, or behaviors. They follow a convention-based loader — each `.py` file in an extensions directory defines a `register()` function.

---

## Architecture

```
ExtensionRegistry.discover()
  │
  ├── Scan ~/.taui/extensions/*.py (global)
  ├── Scan .taui/extensions/*.py (project, overrides global)
  └── Filter: .py files only, skip _-prefixed files
          │
          ▼
ExtensionRegistry.load_all(tools, commands)
  │
  ├── Import each extension module via importlib
  ├── Call register(tools=ToolRegistry, commands=CommandRegistry)
  ├── Catch exceptions per-extension (isolation)
  └── Log results (loaded / failed / missing register())
```

---

## Extension Layout

```
.taui/extensions/
├── todo_counter.py   # Custom tool
├── deploy.py         # Custom slash command
└── _helpers.py       # Skipped (_-prefixed)
```

Each file must define:

```python
def register(tools, commands):
    """Called by the extension loader at startup.

    Args:
        tools: ToolRegistry — register custom tools
        commands: CommandRegistry — register custom commands
    """
    tools.register(MyCustomTool())
    commands.register(MyCommand())
```

---

## Discovery Paths

| Scope | Path | Precedence |
|-------|------|------------|
| Global | `~/.taui/extensions/*.py` | Loaded first |
| Project | `.taui/extensions/*.py` | Overrides global (same name) |

Files prefixed with `_` are ignored (helpers, utilities). Non-`.py` files are ignored.

---

## Extension Dataclass

```python
@dataclass(slots=True)
class Extension:
    name: str           # Filename stem (without .py)
    path: Path          # Full path to the .py file
    scope: str          # "global" or "project"
    enabled: bool       # Whether to load (default True)
    loaded: bool        # Whether register() succeeded
    error: str | None   # Error message if loading failed
```

---

## Loading Behavior

1. **Import**: `importlib.util.spec_from_file_location()` loads the module
2. **Call**: `register(tools=..., commands=...)` is called
3. **Isolation**: Exceptions are caught per-extension — a broken extension doesn't prevent others from loading
4. **Idempotent**: `load_all()` skips already-loaded extensions

### Module Naming

Extension modules are loaded as `taui_ext_{name}` in `sys.modules` to avoid collisions with core modules.

---

## Wiring (Session.create)

```python
ext_registry = ExtensionRegistry(config.working_dir)
ext_registry.discover()
ext_registry.load_all(tools=registry, commands=None)
```

Extensions are loaded after all builtin tools are registered and wired, so they can use `tools.register_or_replace()` to override builtins if needed.

The command registry is wired later in the CLI layer, so `commands` is passed as `None` during session creation. The `/extensions` command provides runtime visibility.

---

## /extensions Command

The `/extensions` slash command lists all discovered extensions and their status:

```
Extensions (3):
  deploy [project] — loaded
  todo_counter [project] — loaded
  broken_ext [global] — error
    error: SyntaxError: invalid syntax
```

---

## Self-Edit Mode (/i)

The `/i` command enters self-edit mode where the agent can create extensions. See [self-edit.md](self-edit.md) for the full design.

When in `/i` mode, the agent:
1. Generates a `.py` file implementing the extension
2. Writes it to `.taui/extensions/` (project) or `~/.taui/extensions/` (global)
3. The extension is available on next session start

---

## Recovery

- `--no-extensions` CLI flag skips all extension loading
- Broken extensions are logged and skipped — core always starts
- `/extensions` shows which extensions failed and why

---

## Example: Custom Tool Extension

```python
# .taui/extensions/todo_counter.py
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult

@dataclass
class TodoCounter:
    name: str = "todo_count"
    description: str = "Count TODO comments in the codebase"
    category: ToolCategory = ToolCategory.SEARCH
    guidelines: str = "Use to get an overview of remaining TODOs."
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Pattern to search for (default: TODO)",
            }
        },
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import subprocess
        pattern = arguments.get("pattern", "TODO")
        result = subprocess.run(
            ["grep", "-r", "--count", pattern, "."],
            capture_output=True, text=True
        )
        return ToolResult.ok(result.stdout or "No matches found.")

def register(tools, commands):
    tools.register(TodoCounter())
```

## Example: Custom Command Extension

```python
# .taui/extensions/deploy.py
from dataclasses import dataclass
from taui.commands.registry import CommandContext, CommandResult

@dataclass(slots=True)
class DeployCommand:
    name: str = "deploy"
    description: str = "Run project deploy script"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        import subprocess
        result = subprocess.run(["./deploy.sh"], capture_output=True, text=True)
        if result.returncode == 0:
            return CommandResult.ok(result.stdout)
        return CommandResult.fail(result.stderr)

def register(tools, commands):
    commands.register(DeployCommand())
```
