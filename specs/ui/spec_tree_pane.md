# Spec Tree Pane

Define editable outline rendering, canonical spec references, and hierarchy controls.

{{status: in-progress}}

- [specs/ui/spec_tree_pane.md#spec-tree-pane](spec_tree_pane.md#spec-tree-pane)
- [Edit selected outline entry text](spec_tree_pane.md#edit-selected-outline-entry-text)
- [Traverse and render visible outline order](spec_tree_pane.md#traverse-and-render-visible-outline-order)
- [Apply Tab and Shift+Tab hierarchy changes](spec_tree_pane.md#apply-tab-and-shifttab-hierarchy-changes)

## Edit selected outline entry text

Apply keyboard text edits to the selected outline entry while keeping canonical spec reference synchronized.

{{status: in-progress}}

- [specs/ui/spec_tree_pane.md#edit-selected-outline-entry-text](spec_tree_pane.md#edit-selected-outline-entry-text)

### Edit selected outline entry text leaf
{{status: in-progress}}

- Typing updates selected text and keeps canonical `spec_ref` synchronized.
{{code_ref: `taui/static/js/tree.js`}}
## Traverse and render visible outline order

Render and navigate only the visible outline sequence from expanded branches.

{{status: in-progress}}

- [specs/ui/spec_tree_pane.md#traverse-and-render-visible-outline-order](spec_tree_pane.md#traverse-and-render-visible-outline-order)

### Traverse and render visible outline order leaf
{{status: in-progress}}

- Collapsed descendants stay hidden and excluded from Up and Down traversal.
{{code_ref: `taui/static/js/tree.js`}}
## Apply Tab and Shift+Tab hierarchy changes

Use Tab and Shift+Tab to adjust depth while preserving focus continuity.

{{status: in-progress}}

- [specs/ui/spec_tree_pane.md#apply-tab-and-shifttab-hierarchy-changes](spec_tree_pane.md#apply-tab-and-shifttab-hierarchy-changes)

### Apply Tab and Shift+Tab hierarchy changes leaf
{{status: in-progress}}

- Tab nests under previous sibling and keeps edited entry visible.
- Shift+Tab promotes one depth level and keeps focus on moved entry.
{{code_ref: `taui/static/js/state.js`}}
