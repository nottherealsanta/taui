## Active playbook: add tool

The user wants to add a new tool. Tools are added via the **extension route** —
never as standalone modules. Concretely, you write a single Python file at:

- Project scope: `.taui/extensions/tool_<slug>.py`
- Global scope: `~/.taui/extensions/tool_<slug>.py`

Pick the scope that matches the panel's `scope` line (the user can change it with
`scope project` / `scope global`).

### Tool contract

Every tool implements the `Tool` protocol (`taui/tools/base.py`):

```python
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class GitBranchTool:
    name: str = "git_branch"
    description: str = "Return the current git branch."
    category: ToolCategory = ToolCategory.GIT
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import subprocess
        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
            return ToolResult.ok(out)
        except subprocess.CalledProcessError as exc:
            return ToolResult.fail(str(exc))


def register(ctx):
    ctx.tools.register(GitBranchTool())
```

Notes:

- `name` is the lowercase identifier the LLM will use to call the tool.
- `description` is shown to the LLM in the tool index — keep it accurate and short.
- `category` is one of the `ToolCategory` enum values (e.g. `GIT`, `SHELL`,
  `SEARCH`, `FILE_READ`, `FILE_WRITE`, `MEMORY`, `QUESTION`, `AGENT`).
- `schema` is a JSON Schema describing the arguments the tool accepts.
- `execute` is async and must return a `ToolResult` (`ToolResult.ok(text)` or
  `ToolResult.fail(text)`).
- `register(ctx)` is the entry point. `ctx.tools.register(...)` adds the tool to
  the active registry. Legacy `register(tools, commands, hooks)` also works.

### Workflow

1. Confirm with the user what the tool should do, what inputs it takes, and what
   it should return.
2. Pick a slug. The file path must be unique — if a `tool_<slug>.py` already
   exists, append a numeric suffix.
3. Write the file with `Write`.
4. Tell the user to run `/q` (or `reload`) for the new tool to be callable.

Do not edit `taui/` source. Do not register the tool anywhere except inside the
extension's `register(ctx)` function.
