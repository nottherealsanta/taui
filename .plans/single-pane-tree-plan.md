# Single-Pane Tree UX with Inline Editing, Folding, Code Preview, and Terminal

## Summary
- Keep Taui as a single-pane, tree-first interface.
- Make each node inline-editable with Milkdown (full markdown content).
- Add first-class fold/unfold on every parent node to hide/show children.
- Keep CodeMirror (read-only) and xterm in a collapsible bottom drawer with tabs.

## Implementation Changes
- Tree and editing UX:
  1. Preserve current tree as the primary view.
  2. Add chevron controls on rows with children; click chevron toggles fold/unfold.
  3. Keep keyboard fold toggle shortcut and align behavior with chevron click.
  4. Use `spec_ref` as the fold-state key and persist fold state in `localStorage`; restore on load/tree refresh.
  5. Inline Milkdown editor for the active node:
     - Load from `spec/getNode` (`content`)
     - Save with `spec/updateNode` (`patch.content`)
     - One active editable node at a time, with save/discard handling on node switch.

- Bottom drawer tabs (single-pane secondary tools):
  1. `Code` tab: read-only CodeMirror.
     - Display `<file_path>:<line_start>-<line_end>`
     - Default collapsed preview: max 10 lines
     - Click `Expand` for full node range, `Collapse` back to 10 lines
  2. `Terminal` tab: xterm with command input and Run/Stop controls.

- Backend RPC additions/updates:
  1. Add `spec/getNodeSourceRange(spec_ref, expanded=false, max_lines=10)` returning:
     - `file_path`, `line_start`, `line_end`, `preview_start`, `preview_end`, `content`, `truncated`
  2. Upgrade `run/start`, `run/status`, `run/stop` to manage real command execution.
  3. Add notifications:
     - `run/output` for stdout/stderr chunks
     - `run/completed` for final status/exit code
  4. Enforce workspace path validation for source range reads and command `workdir`.

- Build/tooling:
  1. Introduce Vite bundling for Milkdown, CodeMirror, and xterm.
  2. Continue serving built static assets through existing FastAPI static routes.

## Public Interface Changes
- New RPC: `spec/getNodeSourceRange`
- Expanded RPC lifecycle: `run/start`, `run/status`, `run/stop`
- New notifications: `run/output`, `run/completed`
- No backend API needed for fold state (client-managed persistence).

## Test Plan
1. Tree folding:
   - Chevron toggles children visibility
   - Keyboard toggle parity
   - Fold state survives reload via `localStorage`
2. Inline editor:
   - Node content loads into Milkdown and saves correctly
   - Node switch prompts save/discard when dirty
3. Code preview:
   - 10-line default view
   - Expand/collapse behavior
   - Correct file/range labeling
4. Terminal:
   - Live output streaming, completion event, and stop behavior
5. Backend:
   - Source-range bounds and workspace-safety checks
   - Run lifecycle and streaming notifications

## Assumptions
- Single-pane means tree remains dominant; code/terminal are in a bottom drawer.
- Fold state is persisted per node (`spec_ref`) in browser storage.
- Terminal is non-interactive streaming (no full PTY input session).
- If line bounds are missing, code preview falls back to first 10 file lines (expand shows full file).
