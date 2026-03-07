# Spec Tree Interaction

Define behavior-first editing and traversal semantics for spec-tree workflows.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#spec-tree-interaction](spec_tree_interaction.md#spec-tree-interaction)
- [Define terminology and editing modes](spec_tree_interaction.md#define-terminology-and-editing-modes)
- [Define editing entry exit and commit boundaries](spec_tree_interaction.md#define-editing-entry-exit-and-commit-boundaries)
- [Apply Enter Shift+Enter and Tab interaction semantics](spec_tree_interaction.md#apply-enter-shiftenter-and-tab-interaction-semantics)
- [Apply boundary-aware arrow and lateral transitions](spec_tree_interaction.md#apply-boundary-aware-arrow-and-lateral-transitions)
- [Apply transient UI key precedence](spec_tree_interaction.md#apply-transient-ui-key-precedence)
- [Guarantee deterministic focus and persistence](spec_tree_interaction.md#guarantee-deterministic-focus-and-persistence)

## Define terminology and editing modes

Use shared terminology for outline entries, visible outline order, and mode transitions.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#define-terminology-and-editing-modes](spec_tree_interaction.md#define-terminology-and-editing-modes)

### Define terminology and editing modes leaf
{{status: in-progress}}

- Editing mode: text input mutates current outline entry content.
- Selection mode: movement targets outline structure and focus changes.
- Visible outline order includes expanded descendants and excludes collapsed descendants.

## Define editing entry exit and commit boundaries

Define when editing starts, when it exits, and when pending text must persist before structural moves.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#define-editing-entry-exit-and-commit-boundaries](spec_tree_interaction.md#define-editing-entry-exit-and-commit-boundaries)

### Define editing entry exit and commit boundaries leaf
{{status: in-progress}}

- Editing starts on click selection, keyboard landing, or structural create or split.
- Editing exits on explicit mode transition or focus movement.
- Pending edits persist before structural transition and boundary traversal.
{{code_ref: `taui/static/js/state.js`}}
{{code_ref: `taui/static/js/state.js`}}
## Apply Enter Shift+Enter and Tab interaction semantics

Define structural create or split flow, inline newline flow, and child-creation depth flow.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#apply-enter-shiftenter-and-tab-interaction-semantics](spec_tree_interaction.md#apply-enter-shiftenter-and-tab-interaction-semantics)

### Apply Enter Shift+Enter and Tab interaction semantics leaf
{{status: in-progress}}

- Enter finalizes current content and creates or splits to the next editable outline entry.
- Shift+Enter inserts newline in the same outline entry.
- Tab nests under nearest valid previous sibling and reveals collapsed parent when needed.
{{code_ref: `taui/static/js/state.js`}}
## Apply boundary-aware arrow and lateral transitions

Use text-first boundary logic for Up and Down and safe state transitions for Left and Right.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#apply-boundary-aware-arrow-and-lateral-transitions](spec_tree_interaction.md#apply-boundary-aware-arrow-and-lateral-transitions)

### Apply boundary-aware arrow and lateral transitions leaf
{{status: in-progress}}

- Up and Down traverse previous or next visible outline entry only at text boundaries.
- Left and Right at absolute boundaries change state only and never create or delete structure.
- Collapsed descendants are skipped during traversal until explicitly revealed.
{{code_ref: `taui/static/js/state.js`}}
## Apply transient UI key precedence

Route Enter and arrows to transient UI handlers before editing and structure handlers.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#apply-transient-ui-key-precedence](spec_tree_interaction.md#apply-transient-ui-key-precedence)

### Apply transient UI key precedence leaf
{{status: in-progress}}

- Active autocomplete or menu interactions consume Enter and arrows before outline handling.
{{code_ref: `taui/static/js/keys.js`}}
## Guarantee deterministic focus and persistence

Guarantee visible caret target and persisted edits for every structural movement.

{{status: in-progress}}

- [specs/ui/spec_tree_interaction.md#guarantee-deterministic-focus-and-persistence](spec_tree_interaction.md#guarantee-deterministic-focus-and-persistence)

### Guarantee deterministic focus and persistence leaf
{{status: in-progress}}

- Structural transitions never drop unsaved edits.
- Every traversal leaves a deterministic focused entry with visible caret placement.
{{code_ref: `taui/static/js/state.js`}}
