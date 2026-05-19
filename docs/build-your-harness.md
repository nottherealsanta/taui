# Build Your Harness

Taui customization is extension-first. Drop a Python file into an extension directory,
define `register(ctx)`, and reload.

## Locations

- Global extensions: `~/.taui/extensions/*.py`
- Project extensions: `.taui/extensions/*.py`
- Discovery and precedence: `taui/extensions/__init__.py:116`
- Loading and isolation: `taui/extensions/__init__.py:169`

Files beginning with `_` are ignored. Project extensions override global extensions with
the same file stem.

## `register(ctx)`

`ExtensionContext` is defined at `taui/extensions/__init__.py:66`.

Available targets:

| Target | Purpose | Code |
| --- | --- | --- |
| `ctx.tools` | register or replace tools | `taui/tools/registry.py:10` |
| `ctx.commands` | register slash commands when a command registry is present | `taui/commands/registry.py:60` |
| `ctx.hooks` | add hook handlers | `taui/hooks.py:46` |
| `ctx.policy` | set tool policy or permissions | `taui/tools/executor.py:42` |
| `ctx.skills` | add skill files | `taui/extensions/__init__.py:50` |
| `ctx.agents` | register agent variants | `taui/agent/variants.py:24` |
| `ctx.context` | register context strategies | `taui/agent/context_strategy.py:11` |
| `ctx.providers` | register provider metadata | `taui/extensions/__init__.py:66` |

Minimal extension:

```python
def register(ctx):
    ctx.skills.add_path("skills/reviewer/SKILL.md")
```

## Tools

Tool protocol and result helpers are in `taui/tools/base.py:24` and
`taui/tools/base.py:52`.

```python
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class WordCountTool:
    name: str = "word_count"
    description: str = "Count words in text."
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(str(len(arguments.get("text", "").split())))


def register(ctx):
    ctx.tools.register(WordCountTool())
```

Expected user-facing failures should return `ToolResult.fail()`, not raise:
`taui/tools/base.py:34`.

## Commands

Slash commands implement the registry contract in `taui/commands/registry.py:12`.
Builtins are registered at `taui/commands/builtins.py:858`.

Guard command registration because extension loading can happen without a TUI command
registry:

```python
def register(ctx):
    if ctx.commands:
        ctx.commands.register(MyCommand())
```

## Hooks

Use hooks for observation or controlled transforms. Registry behavior is in
`taui/hooks.py:54` and `taui/hooks.py:120`.

Common hooks are documented in `docs/extension-hooks.md:1`.

## Skills

Skill files are discovered by `taui/skills/__init__.py:91` and lazily loaded by
`taui/skills/__init__.py:52`.

Bundle a skill relative to the extension file:

```python
def register(ctx):
    ctx.skills.add_path("skills/code-review/SKILL.md")
```

## Agents

Agent variants are small named profiles defined by `AgentVariant`:
`taui/agent/variants.py:11`.

```python
from taui.agent.variants import AgentVariant


def register(ctx):
    ctx.agents.register(AgentVariant(
        name="review",
        description="Read-only reviewer",
        read_only=True,
        system_prompt="Review the code. Do not edit files.",
    ))
```

The active session applies variants in `Session.switch_variant()`:
`taui/session.py:940`.

## Safety Rules

- Keep extensions small and import-light; a bad extension is logged and skipped:
  `taui/extensions/__init__.py:169`.
- Register tools through `ToolRegistry`; do not mutate executor internals:
  `taui/tools/registry.py:27`.
- Use `ToolResult.fail()` for normal failures: `taui/tools/base.py:34`.
- Use permission rules for auto-approval rather than bypassing policy:
  `taui/permissions.py:38`.
