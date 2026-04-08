# Spec-Only UI Plan

## Summary
- Make the app spec-focused instead of file-browser-focused.
- Left sidebar shows the structure inside `specs/` using folders and headings, not raw `.md` files.
- Main pane splits into two columns:
  - left: tabbed spec editor with live markdown preview/editing in one surface
  - right: tabbed agent panel for parallel agent runs
- Message bar stays at the bottom of the main pane.

## Target Layout

```text
┌─ TitleBar ────────────────────────────────────────────────┐
├─ Left Sidebar ──┬─ Main Pane ─────────────────────────────┤
│                 │  ┌─ Left Main ──────┬─ Right Main ────┐ │
│ Spec Nav Tree   │  │ Spec Tab Bar     │ Agent Tab Bar   │ │
│ (folders +      │  │                  │                 │ │
│ headings, no    │  │ Live Markdown    │ Agent Detail    │ │
│ .md suffixes)   │  │ Editor           │ Panel           │ │
│                 │  │                  │                 │ │
│                 │  ├──────────────────┴─────────────────┤ │
│                 │  │ MessageBar                         │ │
│                 │  └────────────────────────────────────┘ │
└─────────────────┴─────────────────────────────────────────┘
```

## Requirements

### 1. Left Sidebar: Specs Only
- Replace the current file tree sidebar with a spec navigation sidebar.
- Show everything inside `specs/`.
- Do not show raw `.md` filenames.
- Show folders and headings instead.
- Example navigation shape:
  - `Domains`
  - `Auth`
  - `DB`
- Start with all folders expanded by default.
- Preserve collapse state after the first load via local storage.

### 2. Main Pane Structure
- Replace the current center pane + right sidebar layout with a dedicated main pane.
- Main pane should have two vertical sections:
  - left section for spec content
  - right section for agent content
- Bottom of the main pane should contain the user input area for the agent.

### 3. Left Main Pane: Spec Tabs
- Left main pane should support tabs for multiple open spec files.
- Clicking an item in the spec sidebar opens or activates that spec tab.
- Each tab shows the spec content in a single live editing surface.

### 4. Right Main Pane: Agent Tabs
- Right main pane should support tabs for multiple running agents in parallel.
- Each agent tab shows the event stream and details for that agent.
- The active tab determines where message bar input is sent.

### 5. Unified Markdown Editing Surface
- Remove the current Source / Preview split.
- Replace it with a single editor that previews and edits in place.
- The editor must preserve markdown semantics while selectively revealing syntax near the cursor.

Examples:
- When editing a heading line, show `#` markers while still rendering the line with heading typography.
- When editing bold text, show `**` only when the cursor is adjacent to or inside the bold span, while keeping the text bold.

This should behave like a live-preview markdown editor rather than a separate raw-source editor.

## Implementation Plan

### Phase 1: Sidebar and Navigation Model
1. Create `SpecNavSidebar.svelte`.
2. Build sidebar data from parsed spec structure rather than generic `fs/listDir` output.
3. Map `specs/` folders into labeled sections such as `Domains`, `Features`, and `Decisions`.
4. Show heading-derived display names instead of `.md` filenames.
5. Open all folders by default on first load.
6. Preserve subsequent collapse state locally.

### Phase 2: Main Pane Restructure
1. Create `MainPane.svelte` as the new main workspace shell.
2. Split it into:
   - `SpecEditorPane.svelte` on the left
   - `AgentPane.svelte` on the right
3. Move `MessageBar` into the bottom of `MainPane`.
4. Remove the current `RightSidebar`-driven layout.

### Phase 3: Spec Editor Tabs
1. Rework the tab model around spec files.
2. Clicking a sidebar entry opens or focuses the corresponding spec tab.
3. Keep multiple spec tabs open.
4. Save the active spec file through the existing backend file/spec APIs.

### Phase 4: Agent Tabs
1. Create `AgentPane.svelte`.
2. Add one tab per running agent.
3. Render `AgentDetailPanel` inside the active tab.
4. Route message bar submissions to the active agent tab.

### Phase 5: Live Markdown Editor
1. Replace `MarkdownEditor.svelte` for specs with a unified markdown editor.
2. Use CodeMirror 6 for the spec editor.
3. Implement markdown syntax hiding/revealing with decorations.
4. Keep semantic styling active even when syntax markers are hidden.
5. Reveal markdown markers only near the current selection/cursor.

## Technical Approach

### Sidebar Data Source
- Prefer the parsed spec tree already available in app state.
- Do not drive the primary spec sidebar from the generic workspace file tree.
- The sidebar should reflect spec structure, not arbitrary workspace files.

### Editor Technology Choice
- Use CodeMirror 6 for the live markdown editor.
- Reason:
  - decoration-based rendering is a natural fit for hiding and revealing markdown syntax
  - this matches the required heading and bold behavior closely
  - Monaco is not a good fit for this live-preview interaction model
- Keep Monaco for code previews and diffs where it already works well.

### Collapse Defaults
- Change initial hydration so spec folders/sections are expanded by default.
- Let persisted local state override that after first interaction.

## Files To Create
- `.plans/spec_only_ui_plan.md`
- `app/src/lib/components/SpecNavSidebar.svelte`
- `app/src/lib/components/MainPane.svelte`
- `app/src/lib/components/SpecEditorPane.svelte`
- `app/src/lib/components/AgentPane.svelte`
- `app/src/lib/components/LiveMarkdownEditor.svelte`

## Files To Update
- `app/src/App.svelte`
- `app/src/lib/stores/app-state.svelte.ts`
- `app/src/lib/stores/tabs.svelte.ts`
- `app/package.json`

## Files Likely To Remove Or Retire
- `app/src/lib/components/FileTreeSidebar.svelte`
- `app/src/lib/components/FileTreeItem.svelte`
- `app/src/lib/components/MarkdownEditor.svelte`
- `app/src/lib/components/EditorPane.svelte`
- `app/src/lib/components/RightSidebar.svelte`

## Verification
1. Left sidebar only shows `specs/` content.
2. Sidebar shows folders and headings, not `.md` filenames.
3. All folders start expanded by default.
4. Clicking a sidebar entry opens the matching spec in a left-pane tab.
5. Multiple spec tabs can remain open.
6. Multiple agents can run in parallel with one tab per agent on the right.
7. Message bar sits at the bottom of the main pane and targets the active agent tab.
8. Headings render with heading typography while showing `#` only near the cursor.
9. Bold text remains bold while showing `**` only near the cursor.
10. App builds successfully after the layout and editor changes.

## Notes
- This plan intentionally shifts Taui from a generic workspace browser toward a spec-first interface.
- The sidebar is for navigating the spec knowledge surface.
- The main pane is for editing specs and coordinating parallel agents.