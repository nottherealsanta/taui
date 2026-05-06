# Self-Edit Redesign Plan

## Goal

Replace the current full-screen `SelfEditView` (tabbed widget that hides the chat log) with a lightweight **self-edit mode** layered over the existing chat window. Users enter the mode, run short verbs to inspect/create/edit agents, tools, extensions, skills, and config, and exit with hot-reload.

## Current state (baseline)

- `taui/tui/widgets/self_edit.py` — ~1700 LOC. Contains:
  - `SelfEditView` (Vertical) — tabbed UI with Agents / Tools / Extensions / Config panes, sidebars, in-pane editors.
  - `NewAgentScreen`, `NewToolScreen`, `NewExtensionScreen` — modal forms.
  - `SelfEditStore` — disk persistence (`.taui/self_edit/agents.json`, scope state).
  - `AgentProfile`, `ToolSource`, `ExtensionSource`, `_DEFAULT_AGENTS`.
  - Scaffolding helpers (`_tool_extension_template`, `_extension_template`, slug/title/id-from-prompt helpers).
- `taui/tui/app.py`:
  - `_self_edit_mode: bool` flag.
  - `Ctrl+I` binding → `action_open_self_edit` mounts `SelfEditView`, hides chat log + input.
  - `action_close_self_edit` removes it.
  - `/q` in self-edit mode closes the view (line ~556).
  - `self_edit_open` command action (line ~586).

## Target UX

### Entry / exit
- `/i` toggles self-edit mode **on**. Chat log stays visible — history and context are preserved.
- `/q` exits self-edit mode and triggers hot reload (`session.reload_extensions()` + `_wire_callbacks()`).
- `Esc` at the top level (no active modal) also exits.
- `/quit` / `Ctrl+C` still quits the app, regardless of mode.
- Re-binding: drop `Ctrl+I` (replaced by `/i` slash command). Keep the keybinding only if we want a hotkey path.

### Visual indicator
- 1-row `Static` mounted above `#chat-input` showing `////////////////////////////////////` in `#f0c808` (existing accent color).
- Chat input border / prompt char tints yellow while in mode.
- Implemented as a new `SelfEditStatusBar` widget in `taui/self_edit/status_bar.py`, mounted/unmounted by mode toggle.

### Verbs (typed into chat input while in mode)
Verbs are unprefixed (no `/`) since the whole mode is self-edit:

| Verb | Effect |
| --- | --- |
| `agents` | List all agents (id, name, scope, model). |
| `agent <ID>` | Show one agent's details (prompt file path, allowed tools, model). |
| `tools` | List all tools (built-in + custom), source path. |
| `tool <name>` | Show tool details (category, schema, source). |
| `extensions` | List discovered extensions, scope, load status. |
| `extension <name>` | Show extension details + path. |
| `skills` | List available skills (read-only for now). |
| `config` | Show current runtime config (provider, model, max_turns, system prompt). |
| `new agent` | Begin agent creation flow (prompts for name + body). |
| `new tool` | Begin tool creation flow. |
| `new extension` | Begin extension creation flow. |
| `edit agent <ID>` | Open prompt `.md` in `FileEditModal`. |
| `edit tool <name>` | Open tool source `.py` in modal (built-ins are read-only). |
| `edit extension <name>` | Open extension source `.py` in modal. |
| `edit config` | Open config form modal (structured fields). |
| `activate <ID>` | Activate an agent profile (rebuild loop with profile's tools/model/prompt). |
| `scope project` / `scope global` | Set creation scope (sticky for the session). |
| `reload` | Force reload now without exiting mode. |
| `cancel` | Cancel pending creation flow. |
| `help` | Print verb reference. |
| `/q` | Exit mode + reload. |

Anything not matching a verb prints a hint into the chat log. The agent loop is **not** invoked while in self-edit mode; bare text is consumed by an active creation flow if one is pending, otherwise treated as an unknown verb.

### Editing files: markdown / source modal
- `edit agent BLD` opens a `ModalScreen` (`FileEditModal`) containing a `TextArea` loaded from the file.
  - `Ctrl+S` saves.
  - `Esc` cancels (with confirm if dirty).
  - Title bar shows the path.
  - Language hint (`markdown` for prompts, `python` for tool/extension source) drives `TextArea.language`.
- One generic modal replaces the three current `New*Screen` modals and the in-pane editors.
- Saving the modal **does not** hot-reload — only `/q` or explicit `reload` triggers reload. Lets users make several edits cheaply before paying the reload cost.

### Storage shape change
Today `AgentProfile.prompt` is an inline string inside `agents.json`. To make markdown editing meaningful:
- Keep `agents.json` for metadata: `{id, name, provider, model, allowed_tools, prompt_path}`.
- Write prompts to `.taui/self_edit/agents/<ID>.md` (project) or `~/.taui/self_edit/agents/<ID>.md` (global).
- **Migration**: on `SelfEditStore.load_agents`, if a row has `prompt` (inline) and no `prompt_path`, write `<ID>.md` and rewrite the JSON row. Idempotent.
- Default agents (`BLD`, `PLN`) get their `.md` files written on first mode entry if missing.

## Architecture

### File layout
```
taui/self_edit/
  __init__.py
  controller.py     # SelfEditController: parses verbs, dispatches, holds session state
  store.py          # SelfEditStore, AgentProfile, dataclasses (moved from widgets/)
  scaffolding.py    # _tool_extension_template, _extension_template, slug helpers
  modal.py          # FileEditModal (generic), ConfigEditModal (structured)
  status_bar.py     # SelfEditStatusBar widget (yellow //// bar)
  listings.py       # Plain-text formatters for agents/tools/extensions listings
```

`taui/tui/widgets/self_edit.py` is **deleted**.

### App wiring (`taui/tui/app.py`)
- Replace `_self_edit_mode: bool` with `_self_edit: SelfEditSession | None`.
  - `SelfEditSession` holds: `scope`, `pending_creation: PendingCreation | None`, `dirty_files: set[Path]`.
- New early branch in `_handle_command` (or just before it): if `_self_edit` is set, route the input to `SelfEditController.handle(text)` instead of the normal command pipeline / agent loop.
- New methods:
  - `action_enter_self_edit()` — mount status bar, instantiate session + controller, change input styling.
  - `action_exit_self_edit()` — unmount status bar, restore input styling, run reload, drop session.
- Delete `action_open_self_edit`, `action_close_self_edit`, `Ctrl+I` binding, `self_edit_open` command action handler.

### Controller responsibility (`SelfEditController`)
- Parses verbs (split first token, dispatch).
- Each verb is a method returning a string (printed into chat log) and optionally a side effect (open modal, update session state, scaffold files).
- Owns a reference to `SelfEditStore`, `Session`, `Config`, and the `App` (to push modals).
- Pending creation state machine: `new agent` → controller stores `PendingCreation(kind="agent")`, prints "type your prompt; or `cancel`". Next non-verb input completes the flow: scaffold the `.md` + write `agents.json` row → confirmation printed.

### Pending creation flow detail
1. User: `new agent`
2. Controller: prints `enter prompt for new agent (or 'cancel'):`, sets `pending_creation`.
3. User types prompt body (multi-line allowed; for now, single message = single prompt).
4. Controller calls `_agent_id_from_prompt`, `_title_from_prompt`, writes `<ID>.md`, writes JSON row at scope, clears pending state, prints `created agent <ID> at <path>`.

For tools/extensions: same shape, scaffolding helpers already exist in `taui/tui/widgets/self_edit.py` and just need to move to `scaffolding.py`.

### Reload semantics
On `/q` exit:
1. If `dirty_files` non-empty and any failed to save, prompt confirm (later — phase 3).
2. Call `session.reload_extensions()`.
3. Re-wire app callbacks (`self._wire_callbacks()`).
4. If reload reports errors (extension load failures), print them into chat log post-exit.
5. Drop `_self_edit` session.

## What to delete vs. keep

**Delete**
- `taui/tui/widgets/self_edit.py::SelfEditView` and all its CSS / compose / event handlers.
- `NewAgentScreen`, `NewToolScreen`, `NewExtensionScreen`.
- `action_open_self_edit`, `action_close_self_edit`, `_self_edit_mode`, `Ctrl+I` binding, `self_edit_open` command action.

**Keep (move into `taui/self_edit/`)**
- `SelfEditStore` (extend with `prompt_path` migration).
- `AgentProfile`, `ToolSource`, `ExtensionSource`, `NewToolRequest`, `NewExtensionRequest`, `_DEFAULT_AGENTS`.
- Scaffolding: `_tool_extension_template`, `_extension_template`, `_agent_id_from_prompt`, `_slug_from_prompt`, `_title_from_prompt`, `_summary_from_prompt`, `_class_name_from_slug`, `_unique_path`, `_scope_extension_base`, `_infer_tool_category`, `_agent_prompt_from_request`.
- Provider/model option helpers (`_agent_model_options`, `_split_agent_model`, etc.) — used by config + activate flows.

## Implementation phases

### Phase 1 — Mode toggle + status bar + listings
- Create `taui/self_edit/` package; move `SelfEditStore` and dataclasses from `widgets/self_edit.py`.
- Add `SelfEditStatusBar` widget.
- App: `_self_edit` session state, `/i` toggles, `/q` exits with reload.
- Controller: implement `agents`, `tools`, `extensions`, `skills`, `config`, `help`, `cancel`, `scope`, `reload`, `/q`. Listings rendered as plain text via `listings.py`.
- Delete the old `SelfEditView` mounting code (but leave `widgets/self_edit.py` in place for now to avoid touching everything in one PR).
- **Acceptance**: enter mode, list agents, exit with reload. Chat log preserved across toggle.

### Phase 2 — File edit modal + edit verbs
- Implement `FileEditModal(path, language)`.
- Migrate `AgentProfile` storage to per-agent `.md` files. Migration runs on first load.
- Implement `edit agent <ID>`, `edit tool <name>`, `edit extension <name>`. Built-in tools get a read-only modal with a banner.
- Implement `agent <ID>` / `tool <name>` / `extension <name>` detail printers.
- **Acceptance**: edit a prompt in markdown modal, save, exit, agent picks up new prompt after reload.

### Phase 3 — Creation flows + activate + config edit
- Implement `new agent`, `new tool`, `new extension` with pending-creation state machine.
- Implement `activate <ID>` (port logic from `_activate_agent` in old widget).
- Implement `edit config` modal (structured form: provider/model/max_turns/system_prompt). Or split into verbs: `set provider copilot`, `set model …`, `set max-turns 20`. Decide based on UX preference; recommend modal for now.
- Delete `taui/tui/widgets/self_edit.py` entirely.
- **Acceptance**: create new agent end-to-end, activate it, run a normal chat turn against it.

### Phase 4 (optional polish)
- Skills scaffolding (currently read-only).
- Dirty-file warning on `/q`.
- Reload error reporting inline.
- Tab completion for verbs / IDs in `ChatInput` while in self-edit mode.

## Open decisions (confirm before building)

1. **`/q` semantics.** Today `/q` quits the app with branches for ext-mode and self-edit-mode. Proposed: in self-edit mode `/q` always exits to chat, never quits app. `/quit` / `Ctrl+C` quits app. Confirm.
2. **Modal vs verbs for structured fields.** Prompts → markdown modal is clear. For agent metadata (model, allowed_tools), proposing modal with structured fields. Alternative: verbs only (`agent BLD set model …`, `agent BLD allow-tool …`).
3. **Listings rendering.** Plain text in chat log (simple, matches "chat just changes a little") vs mountable widgets with click-to-edit (nicer, reintroduces widget complexity). Proposed: plain text in phase 1; revisit if it feels clunky.
4. **Dirty state on `/q`.** If extension reload fails post-exit, exit and surface the error inline (user re-enters with `/i` to fix). Proposed; no blocking confirm.
5. **Scope sticky vs per-command.** Proposing sticky `scope global` verb (persists for session), default project. Alternative: `--global` flag on each `new` verb.
6. **Skills.** Read-only `skills` listing in phase 1. Scaffolding deferred. Confirm.
7. **`Ctrl+I` keybinding.** Drop entirely or keep as a hotkey alias for `/i`?

## Tests to add / update

Existing: `tests/test_self_edit.py` — covers store, agent loading, scaffolding helpers. Most tests on store + helpers stay valid after the package move. UI-level tests for the old `SelfEditView` are deleted.

New tests:
- `SelfEditController.handle("agents")` returns expected listing string.
- `SelfEditController.handle("new agent")` then prompt body — produces correct file + JSON row.
- Migration: `agents.json` with inline `prompt` field is migrated to `.md` + `prompt_path` on next load.
- Mode toggle: app enters self-edit, status bar mounted; `/q` exits and triggers reload (mocked).
- `FileEditModal` save path writes file; cancel does not.

## Risks / things to watch

- **Reload races.** Hot reload on `/q` runs `reload_extensions()` which may re-instantiate tools the agent loop holds references to. Today this works because the user is between turns; verify the same holds when entering/exiting from mid-conversation.
- **Migration safety.** First load of an old `agents.json` rewrites it. Read-only filesystem (rare) breaks this. Wrap in try/except, leave inline prompts as fallback.
- **Modal stacking.** `ModalScreen` push during pending-creation flows shouldn't conflict with approval modals. Check `app.screen_stack` handling.
- **Cancellation.** If user enters `/i`, opens a modal, then `Ctrl+C`s — make sure modal is dismissed cleanly and mode is exited.
