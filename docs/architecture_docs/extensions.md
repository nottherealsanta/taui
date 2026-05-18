# Extension System

Extensions are Python files that register additional tools, commands, hooks, skills, and
other behaviors. Each `.py` file in an extensions directory exposes a `register(ctx)`
entry point that the loader calls at startup.

---

## Architecture

```
ExtensionRegistry.discover()
  │
  ├── Scan ~/.taui/extensions/*.py       (global)
  ├── Scan .taui/extensions/*.py         (project, overrides global)
  └── Filter: .py only, skip _-prefixed, builtin names reserved
          │
          ▼
ExtensionRegistry.load_all(tools, commands, hooks, policy, agents, context, providers)
  │
  ├── importlib.util.spec_from_file_location() — module named taui_ext_{name}
  ├── Call register(ctx: ExtensionContext)
  ├── Catch all exceptions per-extension (isolation)
  └── Collect skill_paths from ctx.skills after register() returns
```

---

## Discovery Paths

| Scope | Path | Precedence |
|-------|------|------------|
| Global | `~/.taui/extensions/*.py` | Loaded first |
| Project | `.taui/extensions/*.py` | Overrides global (same name) |

Files beginning with `_` are ignored. Non-`.py` files are ignored. Builtin extension
names are reserved — a file with a conflicting name is skipped with a warning.

---

## Extension Layout

```
.taui/extensions/
├── todo_counter.py   # Custom tool
├── deploy.py         # Custom slash command
└── _helpers.py       # Skipped (_-prefixed)
```

---

## register(ctx) Entry Point

Every extension must define:

```python
def register(ctx):
    ctx.tools.register(my_tool)
    if ctx.commands:
        ctx.commands.register(my_cmd)
    ctx.hooks.banner(lambda session: "hello")
    ctx.skills.add_path("skills/my-skill.md")
```

`ctx` is an `ExtensionContext` instance. All fields are optional at call sites — check
before using when the capability may be absent.

---

## ExtensionContext

```python
@dataclass
class ExtensionContext:
    tools: Any                  # ToolRegistry | None
    commands: Any               # CommandRegistry | None
    hooks: Any                  # HookRegistry | None
    policy: Any = None          # ToolPolicy | None
    skills: SkillContribution = field(default_factory=SkillContribution)
    agents: Any = None          # AgentVariantRegistry | None
    context: Any = None         # ContextStrategyRegistry | None  (future)
    providers: Any = None       # ProviderRegistrationProxy | None
```

`skills` is always present. Relative paths passed to `ctx.skills.add_path()` are
resolved against the extension file's own directory.

---

## SkillContribution

```python
class SkillContribution:
    def add_path(self, path: str | Path) -> None: ...
    @property
    def paths(self) -> list[Path]: ...
```

Accumulates skill paths contributed during `register()`. After the call returns,
`ExtensionRegistry` stores the collected paths on the `Extension` dataclass.

---

## Extension Dataclass

```python
@dataclass(slots=True)
class Extension:
    name: str                   # Filename stem (without .py); None path for builtins
    path: Path | None           # Full path to the .py file; None for builtins
    scope: str                  # "global", "project", or "builtin"
    description: str = ""
    enabled: bool = True
    loaded: bool = False        # True after register() succeeds
    error: str | None = None    # Error message if loading failed
    skill_paths: list[Path] = field(default_factory=list)
```

---

## ExtensionRegistry API

| Method / Property | Description |
|-------------------|-------------|
| `discover()` | Scans extension directories, resets the registry |
| `load_all(tools, commands, hooks, policy, agents, context, providers)` | Loads all enabled extensions; returns names of those that loaded |
| `get(name)` | Returns a single `Extension` or `None` |
| `list_all()` | Returns all `Extension` objects in sorted name order |
| `loaded_extensions()` | Returns only extensions where `loaded=True` |
| `unload_all()` | Marks all extensions unloaded and removes modules from `sys.modules` |
| `names` | Sorted list of extension names |

```python
registry = ExtensionRegistry(working_dir, include_builtins=True)
registry.discover()
registry.load_all(tools=tool_registry, commands=cmd_registry, hooks=hook_registry)
```

---

## Module Naming

Extension modules are loaded under the name `taui_ext_{name}` in `sys.modules`. This
prevents collisions with first-party packages. On `unload_all()` these entries are
removed so a subsequent `load_all()` re-executes the module code cleanly.

---

## Error Isolation

- Exceptions inside `register()` are caught per-extension.
- A broken extension sets `ext.error` and logs a warning; other extensions and the core
  agent loop are unaffected.
- Missing `register()` function sets `ext.error = "Missing register() function"`.
- A broken extension sets `ext.error` and is skipped; the agent starts normally.

---

## /reload Hot-Reload

`/reload` calls `unload_all()` followed by `discover()` and `load_all()` on the live
registry. This picks up new, modified, or deleted extension files without restarting
the session.

---

## /extensions Command

`/extensions` lists every discovered extension and its status:

```
Extensions (3):
  deploy [project] — loaded
  todo_counter [project] — loaded
  broken_ext [global] — error: SyntaxError: invalid syntax
```

---

## Self-Edit Mode (/i)

`/i` enters a specialist loop that writes extension files as its only output. See
[self-edit.md](self-edit.md) for the full design. Created files appear under
`.taui/extensions/` (project scope) or `~/.taui/extensions/` (global scope) and are
available after the next `/reload` or session restart.

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
            "pattern": {"type": "string", "description": "Pattern to search for"},
        },
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import subprocess
        pattern = arguments.get("pattern", "TODO")
        result = subprocess.run(["grep", "-r", "--count", pattern, "."],
                                capture_output=True, text=True)
        return ToolResult.ok(result.stdout or "No matches found.")

def register(ctx):
    ctx.tools.register(TodoCounter())
```

## Example: Bundled Skill Extension

```python
# ~/.taui/extensions/testing_skill.py
def register(ctx):
    ctx.skills.add_path("skills/testing.md")  # resolved relative to this file
```
