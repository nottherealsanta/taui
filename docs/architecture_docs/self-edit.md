# Self-Edit Mode

`/i` enters self-edit mode. The agent operates with a specialist loop, scoped tools, and
playbooks focused on creating and modifying taui configuration. Every output is an
extension file — the core source is never patched.

---

## Extensions, Not Patches

Self-edits produce Python files and skill files. When the agent creates a tool, overrides
a prompt, or registers a command via `/i`, it writes to an extensions directory. Taui
discovers and loads these files at startup and on `/reload`.

This means:

- The user never modifies the Taui source repository.
- Extensions are regular Python files — editable, diffable, version-controllable.
- A broken extension cannot corrupt the core agent loop, the Store, or the transport
  layer.
- Running `taui --no-extensions` always returns to a known-good baseline.

---

## Activation

`/i` replaces the current session's agent loop with a specialist loop that:

1. Loads a static system prompt from `taui/self_edit/prompts/self_edit_system.md`.
2. Prepends a live scope/inventory header (`build_self_edit_system_prompt()`).
3. Uses a scoped `ToolExecutor` with no approval prompts (`PolicyDecision.AUTO` for all
   tools).
4. Restricts available tools to `read`, `edit`, `write`, and `bash`.

`Escape` exits self-edit mode and restores the original loop.

---

## Scoped Tool Restrictions

### File tools (read / edit / write)

All file tools are wrapped with a `PathAllowlist` that limits paths to the self-edit
roots:

- `~/.taui/` (global scope)
- `.taui/` relative to the project working directory (project scope)

Paths outside these roots are rejected. The tools receive normalized absolute paths so
the working-directory restriction of the main session does not interfere.

### bash

Bash is replaced by `_SelfEditBashTool`, a read-only facade that allows only:

```
cat  find  grep  ls  pwd  rg
```

Shell control operators (`; & | < > \`` $(...)``) and redirection are blocked. For
`find`, the mutating flags `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir` are also
blocked. Any disallowed command returns `ToolResult.fail()` immediately without
executing.

---

## Scope Switching (Project vs. Global)

Self-edit writes land in one of two scopes:

| Scope | Root path | When it applies |
|-------|-----------|-----------------|
| Global | `~/.taui/` | Active in every workspace on this machine |
| Project | `.taui/` (relative to working dir) | Active only in the current workspace |

The active scope is persisted by `SelfEditStore` and defaults to `"global"` on first
use. The system prompt header shows the active scope and the corresponding tool working
directory. The user can ask the agent to switch scope, or write to the inactive scope by
using an absolute path.

Project-scoped extensions and skills override global ones with the same name, following
the same most-specific-wins rule as the rest of the extension system.

---

## SelfEditInventory and InventoryRow

`collect_self_edit_inventory(working_dir)` scans disk and returns a `SelfEditInventory`
that is both formatted into the system prompt header and rendered in the TUI.

```python
@dataclass(frozen=True, slots=True)
class InventoryRow:
    label: str           # Category name (e.g. "Skills")
    builtin_label: str   # Count or note for builtins (read-only)
    global_count: int    # Items found under ~/.taui/
    global_path: str     # Human-readable path shown in the table
    project_count: int   # Items found under .taui/
    project_path: str    # Human-readable path shown in the table

@dataclass(frozen=True, slots=True)
class SelfEditInventory:
    active_scope: str
    working_dir: Path
    rows: tuple[InventoryRow, ...]
    fresh: bool           # True when all counts are zero (first-time install)
    skills_note: str      # Reminder about taui-native skill write scope
```

Rows cover: Agents, Tools / Extensions, Skills, MCP servers, Slash commands.

When `fresh=True` a note is added to the prompt header explaining that no user-created
items exist yet.

---

## What Self-Edit Can Create

| Type | Write path | Hot-reload |
|------|-----------|------------|
| Tool / Extension | `{scope}/extensions/<name>.py` | `/reload` |
| Slash command | `{scope}/commands/<name>.py` | `/reload` |
| Skill | `{scope}/skills/<name>/SKILL.md` | `/reload` |
| MCP server entry | `{scope}/mcp.toml` | session restart |
| Agent profile | `{scope}/self_edit/agents.json` | session restart |

Skills can be created and modified under `~/.taui/skills/` or `.taui/skills/`. Agent
Skills standard paths (`.agents/skills/`) are discoverable by Taui but are outside
self-edit's write scope.

---

## What Self-Edit Cannot Touch

The `PathAllowlist` enforces that writes stay inside `~/.taui/` and `.taui/`. This
blocks modification of:

- Taui core source (`taui/`, `tests/`, `pyproject.toml`, etc.)
- Any path outside the two allowed roots

Additionally, the system prompt explicitly instructs the agent never to patch core
modules. Built-in extension names are reserved and cannot be overwritten.

---

## Recovery

- `taui --no-extensions` skips all extension loading; self-edit output files are ignored
  for that session but remain on disk.
- A broken extension produced by self-edit logs a warning and is skipped; the core agent
  loop and other extensions are unaffected.
- `/reload` re-discovers and re-loads all extensions, which clears transient errors if
  the file has been fixed.

---

## build_scoped_tool_registry / build_self_edit_executor

```python
def build_scoped_tool_registry(
    base_registry: ToolRegistry,
    project_working_dir: Path | None = None,
    *,
    scope: str | None = None,
) -> ToolRegistry:
    ...

def build_self_edit_executor(
    base_registry: ToolRegistry,
    base_executor: ToolExecutor,
    project_working_dir: Path | None = None,
) -> ToolExecutor:
    ...
```

`build_scoped_tool_registry` creates fresh tool instances (not shared with the main
session) wrapped with the `PathAllowlist`. `build_self_edit_executor` wraps those tools
in a `ToolExecutor` where every tool is `PolicyDecision.AUTO` so no approval prompts
appear during self-edit.

---

## Reference

- `taui/self_edit/factory.py` — `SelfEditInventory`, `InventoryRow`, tool scoping,
  executor construction, inventory collection
- `taui/self_edit/scoping.py` — `PathAllowlist`, `self_edit_roots`,
  `wrap_tool_with_allowlist`
- `taui/self_edit/store.py` — `SelfEditStore`, active scope persistence
- `taui/self_edit/prompts/self_edit_system.md` — static system prompt body
- [extensions.md](extensions.md) — extension discovery, loading, and the `/reload` flow
- [skills.md](skills.md) — skill discovery and `add_from_path`
