# Self-Edit Redesign Plan (v2)

## Goal

Self-edit mode is a **specialist agent loop** layered over a frozen prior conversation, driven by a pinned panel of selectable inventory rows and a small set of verbs. Verbs split into deterministic controller actions (`show`, `rm`, `activate`, `scope`, `reload`, `help`) and agent-assisted workflows (`add`, `edit`) that swap a curated playbook into the specialist's system prompt and let the agent do the work via normal Read/Write/Edit tools.

## Current state (baseline)

The chat-layer `SelfEditController` from the previous iteration is in place at `taui/self_edit/controller.py` and prints listings/details into the chat log. Verb-form parsing (`agent BLD`, `tool foo`) and creation flows (`new agent`) are working. This v2 plan replaces the print-into-chat UX with a pinned `SelfEditPanel` widget and replaces the templating-only `add`/`edit` flow with playbook-driven agent assistance.

What stays from v1:
- `taui/self_edit/{store,scaffolding,modal,status_bar,listings}.py` are reusable.
- Verb dispatch shape inside `SelfEditController` stays; bodies change.
- `_self_edit` session state on `TauiApp`, `/i` enter, `/q` exit, `_wire_callbacks` re-wire.

What changes:
- Output sinks: most listings move into the panel; only `show` and verb confirmations print to chat.
- `add` / `edit` are no longer scaffolding-only. They swap playbooks and hand off to a specialist agent loop.
- The user's prior agent loop + any subagents are **frozen** (preserved, not destroyed) on entry, resumed on `/q`.

## UX

### Mode entry / exit

- `/i` → enter self-edit mode:
  - Freeze the current `AgentLoop` (and any in-flight subagents) — preserve their state on the side.
  - Mount `SelfEditPanel` pinned above the chat log; mount `SelfEditStatusBar` above `#chat-input`.
  - Spawn a specialist `AgentLoop` with the same tool registry and `base.md` system prompt; install it via `session._replace_loop`.
- `/new` → clear specialist chat history, keep playbook + selection + specialist instance.
- `/q` → discard specialist loop, run `session.reload_extensions()` + `_wire_callbacks()`, resume the frozen prior loop, unmount panel + status bar.
- `Esc` at top level (no modal) → same as `/q`.
- `/quit` / `Ctrl+C` → quit the app regardless of mode.

### Pinned panel

`SelfEditPanel` is a single `Vertical` widget mounted above `#chat-log`, containing four `Collapsible` sections:

```
┌─ self-edit ────────────────────── scope: project ─┐
│ ▼ Agents (3)                                       │
│     BLD   builder       opus-4-7   .taui/.../BLD.md│  ← selectable rows
│     PLN   planner       sonnet-4   .taui/.../PLN.md│
│     ...                                            │
│ ▶ Tools (12)                                       │
│ ▶ Extensions (4)                                   │
│ ▶ Skills (7)                                       │
└────────────────────────────────────────────────────┘
```

- Each row is a focusable, selectable item. Click or arrow-key + Enter selects.
- **Global selection**: one selection at a time across all sections. Highlighted row is the implicit object for the next verb.
- Sections render counts in the header; expanding lazily renders rows.
- Status footer line shows current scope and active playbook (e.g. `scope: project · playbook: add_tool`).

### Verbs

Typed into the chat input while in self-edit mode. Verbs are bare (no `/` prefix); `/`-prefixed commands keep their normal app meanings (`/new`, `/q`, `/quit`).

| Verb | Kind | Behavior |
| --- | --- | --- |
| `show` | direct | Print selection's file (or a formatted detail block) into chat log. |
| `edit` | agent-assisted | Swap playbook to `edit_<kind>`, agent edits the file via Read/Edit. |
| `add` | agent-assisted | Swap playbook to `add_<kind>`, agent scaffolds via the extension route. |
| `rm` / `delete` | direct | Confirm in chat, delete file, remove JSON row, refresh panel. |
| `activate` | direct | Agents only. Existing `_activate` logic. |
| `scope project` / `scope global` | direct | Set creation scope sticky for the session. |
| `reload` | direct | Force reload now without exiting mode. |
| `help` | direct | Print verb reference contextual to current selection. |
| `cancel` | direct | Clear active playbook back to `base.md`. |
| `/new` | direct | Reset specialist chat history. |
| `/q` | direct | Exit mode + reload + resume prior loop. |

#### Verb resolution

1. If the typed text matches a verb keyword and a row is selected → apply verb to selection's `(kind, target)`.
2. If typed as `verb <kind> <name>` (e.g. `add tool`, `edit agent BLD`) → apply explicitly, no selection needed.
3. If verb requires a selection and none is set and no typed-form provided → print "select a row first or type `<verb> <kind> [name]`".
4. Otherwise (no verb match) → if a playbook is active, send the text to the specialist agent loop. If no playbook is active and no verb match, print "unknown verb; type `help`".

#### Verbs per kind

- **Agents**: `show`, `edit`, `add`, `rm`, `activate`
- **Tools**: `show`, `edit`, `add`, `rm` (built-ins are read-only; `edit` errors with a hint, `rm` errors)
- **Extensions**: `show`, `edit`, `add`, `rm`
- **Skills**: `show`, `add` (read-only otherwise for now)
- **Always available**: `scope`, `reload`, `help`, `cancel`, `/new`, `/q`

### Specialist agent loop

- Same tool registry as normal mode (Read/Write/Edit/Bash/etc.).
- System prompt = `base.md` + (active playbook if any), recomposed every time the playbook changes.
- Owns its own message history. `/new` clears it.
- Frozen prior loop is held on `_self_edit.previous_loop` and restored on `/q`.

### Playbooks

Each playbook is a markdown file at `taui/self_edit/playbooks/<verb>_<kind>.md`. Loaded at controller init; bundled with the package.

- `base.md` — always-on intro. Roughly: "You are taui's self-edit assistant. The user's prior conversation is paused. Modify taui via extensions in `.taui/extensions/`. Be conservative; never delete without confirming. Reload runs on `/q` — until then, your changes are file-edits only."
- `add_tool.md` — explains the extension route for tools. Includes:
  - The `Tool` ABC contract (async, input validation, returns `ToolResult`).
  - The `ExtensionContext` API and `register(ctx)` hook (project root + global locations).
  - The `ToolRegistry.register` site as referenced from extensions.
  - One full working example extension that adds a tool (link/inline).
  - The unique-path / scope rules (`.taui/extensions/tool_<slug>.py` for project, `~/.taui/extensions/tool_<slug>.py` for global).
- `edit_tool.md` — for built-ins, explain why they're read-only and suggest mirroring as a project extension instead. For custom tools, point at the source file and instruct the agent to preserve the registration hook.
- `add_agent.md` — explains `agents.json` row + per-agent `<ID>.md` prompt file under `.taui/self_edit/agents/`.
- `edit_agent.md` — instructs the agent to edit the prompt `.md` file for prompt changes, and `agents.json` row for metadata changes.
- `add_extension.md` — generic extension template + `register(ctx)` hook + scope rules.
- `edit_extension.md` — point at source path; warn about reload semantics.
- `add_skill.md` — skill discovery layout (`.claude/skills/<name>/SKILL.md` etc.) and front-matter contract.

### Direct verb behavior

- **`show`**: agents → render prompt `.md` + metadata block; tools → render source file (`.py`) or built-in detail block; extensions → source file; skills → `SKILL.md`. Always to chat log, fenced for syntax. No LLM.
- **`rm`**: print confirmation prompt in chat (`type 'yes' to delete <path>`). Next user input must be exactly `yes` to proceed; anything else cancels. Built-ins refuse.
- **`activate`**: existing `_activate_agent` logic.
- **`scope`**: existing `_set_scope`.
- **`reload`**: existing `reload`.
- **`help`**: lists verbs applicable to the currently selected kind, plus always-available verbs.
- **`cancel`**: clears active playbook (does not affect specialist chat history).

### Status bar

Existing `SelfEditStatusBar` stays. Add a second status line within the panel footer showing `scope · playbook · selection`.

## Architecture

### File layout

```
taui/self_edit/
  __init__.py
  controller.py        # SelfEditController: verb dispatch, playbook swap, specialist mgmt
  store.py             # SelfEditStore (unchanged from v1)
  scaffolding.py       # template helpers retained but mostly unused by add/edit (agent does it)
  modal.py             # FileEditModal (still used for show fallback if needed)
  status_bar.py        # SelfEditStatusBar
  listings.py          # plain-text formatters for `show` and detail blocks
  panel.py             # NEW: SelfEditPanel + SelectableRow + section helpers
  playbooks/
    base.md
    add_tool.md
    edit_tool.md
    add_agent.md
    edit_agent.md
    add_extension.md
    edit_extension.md
    add_skill.md
```

### App wiring (`taui/tui/app.py`)

- `_self_edit: SelfEditSession | None` (existing) — extend with:
  - `previous_loop: AgentLoop | None`
  - `specialist_loop: AgentLoop | None`
  - `active_playbook: str | None`
  - `selection: Selection | None` where `Selection = (kind, name)`
  - `pending_confirm: PendingConfirm | None` (used by `rm`)
- `action_enter_self_edit()`:
  1. Freeze current loop (`session._loop` → `previous_loop`).
  2. Build specialist loop with same registry, `base.md` system prompt, fresh message history.
  3. Install via `session._replace_loop`.
  4. Mount `SelfEditPanel` and `SelfEditStatusBar`.
  5. Wire panel selection events → controller.
- `action_exit_self_edit()`:
  1. Discard specialist loop.
  2. Restore previous loop via `session._replace_loop(previous_loop)`.
  3. `session.reload_extensions()` + `_wire_callbacks()` + `_update_status()`.
  4. Unmount panel + status bar; drop `_self_edit`.
- Input pipeline: when `_self_edit` is set, route input to `SelfEditController.handle(text)`. The controller decides direct vs agent-handoff and either prints or forwards to the specialist loop.
- `/new` while in mode → controller resets specialist message history.

### `SelfEditController` shape

```python
class SelfEditController:
    async def handle(self, text: str) -> None:
        # 1. Direct slash commands (/q, /new) handled here.
        # 2. Confirmation pending (rm)? consume yes/no.
        # 3. Tokenize → verb form (with optional kind/name).
        # 4. Direct verb? execute, print to chat.
        # 5. Agent-assisted verb? swap playbook on specialist, refresh panel footer.
        # 6. No verb match? if playbook active, forward to specialist; else hint.

    def on_panel_select(self, kind: str, name: str) -> None:
        # Update self._state.selection, update panel footer.
```

### Panel events

- `SelfEditPanel` emits a `RowSelected(kind, name)` message.
- `TauiApp` forwards to `controller.on_panel_select`.
- Panel exposes `refresh()` to re-scan inventory after `add` / `edit` / `rm` agent turns or direct deletions.

### Refresh triggers

- Direct verbs that mutate (`rm`, `activate`) call `panel.refresh()` synchronously.
- Agent-assisted turns: after the specialist loop finishes a turn, controller calls `panel.refresh()` (no extension reload — that waits for `/q`).

### Confirmation flow (rm)

1. User: `rm` (selection: tool `foo`).
2. Controller: prints `delete .taui/extensions/tool_foo.py? type 'yes' to confirm.`, sets `pending_confirm = ("rm", path, kind, name)`.
3. Next user input: if exactly `yes`, perform deletion + refresh; else cancel and print `cancelled`.

### Reload semantics

Unchanged from v1: only `/q` and explicit `reload` trigger `session.reload_extensions()`. The specialist agent's intra-turn writes do not auto-reload; user must `/q` (or `reload`) for them to take effect in the resumed prior loop.

## Defaults locked (no further confirmation needed)

1. Specialist gets the **same tool registry** as the normal loop.
2. **Both** selection-driven and typed-form (`add tool`, `edit agent BLD`) work.
3. `base.md` content as quoted in §Playbooks.
4. Reload **only on `/q`** or explicit `reload`, not per-turn.
5. `add` for tools always uses the **extension route** (`.taui/extensions/tool_<slug>.py`), never standalone modules.

## Implementation phases

### Phase 1 — Panel + selection + loop freeze/spawn + direct verbs

- Implement `SelfEditPanel` with four `Collapsible` sections, `SelectableRow`, `RowSelected` message, `refresh()`.
- Extend `_self_edit` session state with previous/specialist loops, selection, pending_confirm, active_playbook.
- App: freeze prior loop on `/i`, spawn specialist loop with `base.md` only, restore on `/q`.
- Controller: implement `show`, `rm` (with confirm), `activate`, `scope`, `reload`, `help`, `cancel`, `/new`. Wire selection from panel.
- Stub `add` / `edit` to print "playbooks not yet wired" so the UI is exercisable.
- Stub all playbooks as empty files with a TODO line.
- Delete the old print-everything `summary()` path and the v1 verb-only listings (`agents`, `tools`, etc. as listing verbs) since the panel now shows inventory.
- **Acceptance**: enter mode, browse panel, select an agent and run `show`, run `rm` on a custom tool with confirm, exit with `/q`, prior loop resumes mid-conversation.

### Phase 2 — Playbooks + agent-assisted `add` / `edit`

- Author `base.md` and all `add_*` / `edit_*` playbooks.
- Controller: `add` / `edit` swap specialist's system prompt; subsequent freeform input forwards to specialist loop; panel refreshes after each completed turn.
- Built-in tool `edit` returns the "read-only, mirror as extension" message and offers to swap playbook to `add_tool`.
- **Acceptance**: with Tools section selection, `add` swaps to `add_tool`, type "create a tool that returns the current git branch", agent writes a working extension under `.taui/extensions/`, `/q` reloads, normal mode can use the new tool.

### Phase 3 — Polish

- Tab completion in `ChatInput` while in self-edit mode (verbs + selected-kind targets).
- Skills scaffolding playbook completion.
- Inline reload error reporting on `/q`.
- Dirty-state handling if specialist had unfinished tool calls when `/q` fires.

## Tests

Migrated from v1 (still valid):
- `SelfEditStore` migration: inline `prompt` → `prompt_path`.
- Scaffolding helpers (`agent_id_from_prompt`, `slug`, `unique_path`, etc.).

New:
- `SelfEditPanel.refresh()` reflects newly added agents/tools/extensions/skills.
- Selection updates `controller._state.selection`; verbs without selection error appropriately.
- `rm` confirm: only exact `yes` proceeds; anything else cancels.
- Loop freeze/restore: enter mode → `session._loop` is the specialist; `/q` restores the prior reference; prior message history preserved.
- Playbook swap: `add` while Tools selected sets `state.active_playbook == "add_tool"` and the specialist's system prompt contains `base.md` + `add_tool.md`.
- Agent-assisted `add tool` end-to-end (mock LLM): playbook in system prompt, tool calls intercepted, extension file written, panel refresh discovers new tool.

## Risks / things to watch

- **Loop freeze fidelity.** Need to make sure subagents in flight when `/i` fires are truly paused, not dropped. Likely simplest: refuse `/i` while the prior loop has any active turn; print "finish or cancel current turn first."
- **Reload-on-`/q` blast radius.** Specialist's writes have not been reloaded yet; if reload fails, prior loop resumes against possibly-broken extensions. Surface errors inline and keep the user in a state where they can `/i` again to fix.
- **Panel + modal stacking.** `FileEditModal` is no longer the primary edit surface (agent does it), but `show` still benefits from a fenced chat block; consider a modal only as fallback for very large files (>200 lines?).
- **Specialist tool registry mutation.** If the specialist's agent itself adds a new extension via Write, registry doesn't see it until reload. The specialist must be told (in `base.md`) not to expect to call its own newly-written tools mid-session.
- **Selection drift after refresh.** If the selected row disappears after `rm`, clear selection and update footer.
