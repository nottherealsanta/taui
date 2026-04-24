---
title: Progressive Disclosure
last_updated: 2026-04-11
---

# Progressive Disclosure

Collapsible heading sections and nested lists in the tangle editor, so readers see high-level structure first and drill down only when needed.

## Purpose

- Tangle documents are deeply nested — ideas contain sub-ideas, constraints contain exceptions, features contain edge cases.
- Readers should open a document and immediately see high-level structure, not every detail.
- Progressive disclosure makes tangles navigable as trees:
  - Headings collapse by section.
  - Nested list items collapse by branch.
  - Leaves are often code references or detailed behavioral notes.

## User / Business Outcome

- On open, users see the top-level shape of the document first.
  - H1 title remains visible.
  - Section headings (H2+) act as entry points to deeper content.
- Expanding a node reveals only the next level of detail.
  - Child nodes can remain collapsed until explicitly opened.
- No content is lost — collapse state is editor-only and does not affect markdown on disk.

## Scope

- **In scope**
  - Collapsible heading sections (H2+), with H1 treated as non-collapsible title
  - Chevron toggle on list items with nested children (`bulletList` or `orderedList` child)
  - Recursive disclosure: collapsing a parent hides descendants; expanding reveals direct children
  - Chevron rotation animation — right when collapsed, down when expanded
  - Hierarchy border indicator on expanded items with children
  - Keyboard-accessible chevron buttons with `aria-label`s
  - Collapse state remapped correctly when the document is edited
- **Not in scope**
  - Persisting collapse state across sessions (could be added later via editor state serialization)
  - Collapse-all / expand-all toolbar buttons (future enhancement)

## Constraints

- Collapse state is **editor-only** — it must never affect markdown serialization; the markdown roundtrip is preserved perfectly.
  - `app/src/lib/extensions/disclosure-list.ts` — Plugin state is a `Set<number>` that lives entirely in ProseMirror plugin state, never flushed to disk.
- Headings in ProseMirror are flat siblings, not container nodes.
  - Heading section disclosure must compute ranges by scanning top-level nodes between same-or-higher-level headings.
- Chevrons must not interfere with normal list editing (typing, cursor movement, selection).
- ProseMirror's `handleClick` does not fire for `contentEditable=false` widget decorations.
  - Click handling must use direct DOM `mousedown` listeners on the widget elements.
  - `app/src/lib/extensions/disclosure-list.ts` — `handleDOMEvents.mousedown` (line 216) prevents ProseMirror from stealing chevron clicks.
- When the document changes, collapsed positions must be remapped via `tr.mapping.map()` to stay attached to the correct list items.
  - `app/src/lib/extensions/disclosure-list.ts` — `remapCollapsed` (line 132) handles this on every transaction.

## Design

- **Extension architecture** — TipTap extension wrapping a ProseMirror plugin; no schema changes.
  - `app/src/lib/extensions/disclosure-list.ts:DisclosureList`
- **Disclosure layers**
  - Heading sections
    - Detect H2+ heading boundaries by scanning top-level document siblings.
    - Inject heading chevrons and hide section ranges via decorations.
  - Nested list items
    - Add chevrons to list items with nested lists.
    - Hide child list ranges with `disclosure-hidden` decorations.
- **Plugin state**
  - `Set<number>` of collapsed positions keyed by `DISCLOSURE_KEY`.
  - Updated via transaction metadata and remapped on document changes (`tr.mapping.map()`).
  - Full document replacements (for example `setContent`) trigger re-collapse of collapsible nodes in the new doc.
- **Event handling**
  - Each chevron widget attaches its own `mousedown` listener and dispatches a toggle transaction.
  - `handleDOMEvents.mousedown` prevents ProseMirror from consuming chevron clicks.
- **Visual layer**
  - Shared chevron styles for heading and list disclosure.
  - Heading and list nodes use dedicated classes (`.disclosure-heading`, `.disclosure-item`, `.disclosure-hidden`) to control visibility and hierarchy hints.
- **Visual design**
  - Chevron: 12×12 SVG right-pointing arrow; rotates 90° (down) when expanded
  - Opacity 0.6 at rest, 1.0 on hover; color shifts to `--fg-accent` on hover
  - Expanded items with children show a subtle 1px left border (`--border-variant`) to indicate hierarchy
    - `app/src/lib/components/LiveMarkdownEditor.svelte` — CSS for hierarchy border on expanded items (line 438)
  - Collapsed nested content: `display: none` via `disclosure-hidden`
- **Extension registration**
  - `app/src/lib/components/LiveMarkdownEditor.svelte` — DisclosureList import and registration (line 13, line 86)

## Tests / Verification

- All 75 existing tests pass — no regressions introduced.
- Build succeeds with no TypeScript errors.
- Manual verification in the running app:
  - On load, high-level structure is visible first (title + section headings).
  - Expanding an H2 reveals section content while deeper nodes remain collapsed until expanded.
  - Nested list items render chevrons only when children exist.
  - Clicking a chevron collapses/expands recursively.
    - Multi-level nesting: collapsing a grandparent hides descendants.
  - Editing the document while items are collapsed works correctly (positions remap).
  - Chevron rotation animation and hover states display correctly.

## Open Questions

- Should collapse state persist across sessions? Could serialize to `tangles/.taui.db` or a local editor state map.
- Should there be expand-all / collapse-all controls (toolbar or keyboard shortcut)?
- Should users be able to configure the default open depth (for example H2 only vs H2+H3)?

## Related Decisions

None yet — this was a straightforward UI enhancement with no architectural tradeoffs requiring a decision record.
