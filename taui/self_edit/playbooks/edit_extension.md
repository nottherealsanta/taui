## Active playbook: edit extension

The user wants to edit an existing extension.

### Workflow

1. The panel shows the extension's path. Read it with `Read`.
2. Apply changes with `Edit`. Preserve the `register(ctx)` (or
   `register(tools, commands, hooks)`) entry point — without it the extension is
   inert.
3. Reload semantics: extensions only re-register on `/q` or explicit `reload`.
   Tell the user when they should reload.

### Built-in extensions

Built-in extensions (scope `builtin`, no path) cannot be edited directly. If the
user wants to override built-in behavior, write a project-scope extension that
overrides the relevant tool or hook.
