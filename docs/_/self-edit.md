# Self-Edit Mode

`/i` enters self-edit mode. The agent can modify its own tools, prompts, commands, and UI — but every change lands as an extension file, never as a patch to core source code. No fork required.

---

## Extensions, Not Patches

Self-edits produce Python files. When the agent creates a new tool, overrides a prompt, or registers a command through `/i`, it writes a `.py` file to an extensions directory. Taui discovers and loads these files at startup and (where possible) hot-reloads them mid-session.

This means:
- The user never modifies the Taui source repository.
- Extensions are regular Python files — editable, diffable, greppable, version-controllable.
- A broken extension cannot corrupt the core agent loop, the Store, or the transport layer.
- Running `taui --no-extensions` always returns to a known-good baseline.

---

## Extension Scopes

| Scope | Path | When it applies |
|-------|------|-----------------|
| Global | `~/.taui/extensions/` | Active in every workspace |
| Project | `.taui/extensions/` | Active only in this workspace |

Project-scoped extensions override global extensions when they conflict, following the same most-specific-wins rule as tool policies.

---

## What `/i` Can Create

| Extension type | What the agent writes | Example |
|----------------|----------------------|---------|
| **Tool** | Python module exposing a tool function with schema | A `jira_lookup` tool that queries an API |
| **Command** | Python module registering a slash command | `/deploy` that runs a project-specific deploy script |
| **Prompt override** | Python module or text file that replaces or augments a system prompt segment | Changing the agent's tone or adding domain-specific instructions |
| **UI component** | Python module or Svelte component for the Web frontend | A custom pane that renders test coverage |

All extension types follow the same lifecycle: the agent generates the file, writes it to the appropriate extensions directory, logs the event to the Store, and loads it into the running session.

---

## Extension Lifecycle

### Creation

1. User enters `/i` and describes the change.
2. The agent generates a Python file implementing the extension.
3. The file is written to `~/.taui/extensions/` (global) or `.taui/extensions/` (project).
4. A creation event is appended to the Store with the extension name, scope, path, and timestamp.
5. The extension is loaded into the current session.

### Modification

`/i` can replace an existing extension. The replacement is a full file overwrite — no partial patching by the agent. The Store logs each replacement, so any prior version can be reconstructed from the event history.

The user can also edit extension files directly with any editor. Taui does not own these files — it discovers and loads them.

### Removal

An extension can be disabled (Store flag, still on disk) or deleted (file removed). Both are logged. Disabling is preferred for reversibility; the user can re-enable without regenerating.

### Recovery

If an extension causes errors at load time, Taui logs the failure and continues without it. The core system always starts. The user sees which extensions failed and can fix or remove them.

`taui --no-extensions` skips all extension loading entirely.

---

## Loading Order

1. **Core** — always loads, never touched by self-edit.
2. **Global extensions** — `~/.taui/extensions/*`, alphabetical.
3. **Project extensions** — `.taui/extensions/*`, alphabetical.
4. **Conflict resolution** — project overrides global (same name = project wins).

Extensions register themselves through a standard entry point (a `register` function or decorator convention). The loader calls each extension's entry point and catches exceptions so one broken extension cannot prevent others from loading.

---

## What Self-Edit Cannot Touch

The core is protected. `/i` cannot modify:

- The agent loop (think → tool → observe cycle)
- The Store schema or append-only invariant
- The transport layer (WebSocket, JSON-RPC protocol)
- The extension loader itself

These boundaries are enforced by the fact that extensions are loaded code, not patches to core modules. An extension can add a tool or override a prompt, but it cannot monkey-patch the Loop class or alter the Store's write path.

---

## Store vs. Filesystem

The filesystem holds extension **code** — the `.py` files that define tools, commands, and prompts. Code belongs in files where it can be read, edited, and version-controlled.

The Store holds extension **state** — which extensions are active, activation history, the event log of creations and replacements through `/i`. The Store is already an append-only SQLite log, so the full audit trail of self-edits is preserved automatically.

---

## Sharing Extensions

Extensions are files, so sharing is straightforward:

- **Project team** — commit `.taui/extensions/` to the project repo. Teammates get them on pull.
- **Global sharing** — publish an extension as a gist, package, or repo. Others drop it into `~/.taui/extensions/`.
- **Future: `taui install`** — a command that fetches and installs a published extension by name or URL.

---

## Example

User enters `/i` and says: *"Add a tool that counts TODO comments in the codebase."*

The agent:
1. Generates `.taui/extensions/todo_counter.py` containing a tool function with the appropriate schema.
2. Writes the file to disk.
3. Logs the creation to the Store.
4. Registers the tool in the current session's Tool Executor.

From that point on, the agent (and any sub-agents with access to this tool) can call `todo_counter` as a normal tool. The tool persists across sessions because it's a file on disk. If the user deletes the file or disables the extension, the tool disappears.
