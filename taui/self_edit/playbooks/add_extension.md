## Active playbook: add extension

The user wants to add a new extension. Extensions are single Python files at:

- Project: `.taui/extensions/<name>.py`
- Global: `~/.taui/extensions/<name>.py`

Pick the scope shown in the panel footer.

### `register(ctx)` contract

Every extension exposes one entry point:

```python
def register(ctx):
    ctx.tools.register(...)        # add tools
    ctx.commands.register(...)     # add slash commands
    ctx.hooks.banner(...)          # add UI / pipeline / observer hooks
    ctx.skills.add_path("skills/foo.md")  # bundle a skill prompt
```

`ctx` exposes:

- `ctx.tools` — `ToolRegistry`-like; `register(tool_instance)` adds a tool.
- `ctx.commands` — slash command registry (may be `None`).
- `ctx.hooks` — UI/pipeline/observer hook registry. See the extensions system
  prompt in `taui/session.py` for the full hook table.
- `ctx.skills` — used to bundle skill markdown files alongside the extension.

The legacy three-arg form `def register(tools, commands, hooks)` still works.

### Workflow

1. Confirm with the user what the extension does. If it's primarily a tool, use
   the `add_tool` playbook instead.
2. Pick a slug. File must not collide; suffix with a number if needed.
3. Write the file. Keep it small and focused — one extension per file.
4. Tell the user to `/q` (or `reload`) to activate the extension.
