## Active playbook: edit tool

The user wants to edit an existing tool.

### Built-in tools are read-only

If the selected tool's source is `built-in` (no path), do **not** attempt to
modify `taui/` source. Instead, explain to the user that the tool is read-only,
and offer to mirror it as a project extension under `.taui/extensions/tool_<slug>.py`.
If they agree, switch context to the `add_tool` workflow (write a new extension
that overrides or augments the built-in).

### Custom tools

For a tool sourced from `.taui/extensions/<name>.py` or
`~/.taui/extensions/<name>.py`:

1. Read the file with `Read`.
2. Make the requested change with `Edit`.
3. **Preserve the registration hook** — the file must still expose
   `def register(ctx): ctx.tools.register(...)`. If you remove the registered
   instance, the tool will disappear on reload.
4. Tell the user to run `/q` (or `reload`) so the tool is reloaded.

Refer to `add_tool` for the full `Tool` contract.
