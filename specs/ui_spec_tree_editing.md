# UI Spec Tree Editing

Define requirements for editor session state, key priority, and structural navigation semantics.

{{status: ready}}

- [specs/ui_spec_tree_editing.md#ui-spec-tree-editing](ui_spec_tree_editing.md#ui-spec-tree-editing)
- [Track editor session state in app model](ui_spec_tree_editing.md#track-editor-session-state-in-app-model)
- [Prioritize transient-ui key handling](ui_spec_tree_editing.md#prioritize-transient-ui-key-handling)
- [Apply Enter Shift+Enter and Tab semantics](ui_spec_tree_editing.md#apply-enter-shiftenter-and-tab-semantics)
- [Traverse visible nodes with boundary-aware arrows](ui_spec_tree_editing.md#traverse-visible-nodes-with-boundary-aware-arrows)

## Track editor session state in app model

Persist active node, caret, pending edits, mode, and transient-ui activity.

{{status: ready}}

- [specs/ui_spec_tree_editing.md#track-editor-session-state-in-app-model](ui_spec_tree_editing.md#track-editor-session-state-in-app-model)

### Track editor session state in app model leaf
{{status: ready}}

- Selected node and session active node remain synchronized after selection changes.
{{code_ref: `taui/static/js/state.js`}}
## Prioritize transient-ui key handling

Route Enter and arrows to transient UI before text/structure handlers when transient UI is active.

{{status: ready}}

- [specs/ui_spec_tree_editing.md#prioritize-transient-ui-key-handling](ui_spec_tree_editing.md#prioritize-transient-ui-key-handling)

### Prioritize transient-ui key handling leaf
{{status: ready}}

- Transient priority keys are consumed and do not mutate tree state.
{{code_ref: `taui/static/js/keys.js`}}
## Apply Enter Shift+Enter and Tab semantics

Use Enter for structural node creation, Shift+Enter for inline newline, and Tab for indent.

{{status: ready}}

- [specs/ui_spec_tree_editing.md#apply-enter-shiftenter-and-tab-semantics](ui_spec_tree_editing.md#apply-enter-shiftenter-and-tab-semantics)

### Apply Enter Shift+Enter and Tab semantics leaf
{{status: ready}}

- Shift+Enter never creates sibling nodes.
{{code_ref: `taui/static/js/state.js`}}
## Traverse visible nodes with boundary-aware arrows

Keep arrow keys text-first while traversing visible tree order at boundaries.

{{status: ready}}

- [specs/ui_spec_tree_editing.md#traverse-visible-nodes-with-boundary-aware-arrows](ui_spec_tree_editing.md#traverse-visible-nodes-with-boundary-aware-arrows)

### Traverse visible nodes with boundary-aware arrows leaf
{{status: ready}}

- Collapsed descendants are skipped during Up/Down cross-node traversal.

#### Detailed implementation requirements
{{status: ready}}

##### Behavior
{{status: ready}}

- Top and bottom boundaries trigger cross-node movement after commit.

##### Constraints
{{status: ready}}

- Left and right boundary transitions must not create or delete nodes.

##### Files
{{status: ready}}
{{code_ref: `taui/static/js/state.js`}}
{{code_ref: `taui/static/js/state.js`}}
##### Tests
{{status: ready}}

- Cover boundary traversal, collapse skipping, and pending-edit commit semantics.
