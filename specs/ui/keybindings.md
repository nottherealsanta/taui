# Keybindings

Define keyboard behavior contracts for transient UI, text editing, and outline structure actions.

{{status: in-progress}}

- [specs/ui/keybindings.md#keybindings](keybindings.md#keybindings)
- [Apply strict key handling priority](keybindings.md#apply-strict-key-handling-priority)
- [Handle structural keys with deterministic outcomes](keybindings.md#handle-structural-keys-with-deterministic-outcomes)
- [Handle text editing keys without structure mutation](keybindings.md#handle-text-editing-keys-without-structure-mutation)
- [Apply boundary-aware arrow traversal in visible outline order](keybindings.md#apply-boundary-aware-arrow-traversal-in-visible-outline-order)
- [Reserve pane and command shortcuts without conflicts](keybindings.md#reserve-pane-and-command-shortcuts-without-conflicts)

## Apply strict key handling priority

Resolve key handling in this order: transient UI handlers, then editor text handlers, then structure handlers.

{{status: in-progress}}

- [specs/ui/keybindings.md#apply-strict-key-handling-priority](keybindings.md#apply-strict-key-handling-priority)

### Apply strict key handling priority leaf
{{status: in-progress}}

- Enter and arrow keys are consumed by transient UI whenever transient UI is active.
{{code_ref: `taui/static/js/keys.js`}}
## Handle structural keys with deterministic outcomes

Use Enter for create or split flow and Tab or Shift+Tab for depth changes.

{{status: in-progress}}

- [specs/ui/keybindings.md#handle-structural-keys-with-deterministic-outcomes](keybindings.md#handle-structural-keys-with-deterministic-outcomes)

### Handle structural keys with deterministic outcomes leaf
{{status: in-progress}}

- Enter on non-empty text creates the next editable outline entry and moves focus.
- Tab shifts the current entry under the nearest valid previous sibling while keeping focus.
- Shift+Tab moves the current entry up one depth level while keeping focus.
{{code_ref: `taui/static/js/state.js`}}
## Handle text editing keys without structure mutation

Use Shift+Enter to insert inline newline while preserving identity and depth.

{{status: in-progress}}

- [specs/ui/keybindings.md#handle-text-editing-keys-without-structure-mutation](keybindings.md#handle-text-editing-keys-without-structure-mutation)

### Handle text editing keys without structure mutation leaf
{{status: in-progress}}

- Shift+Enter inserts newline in place and never creates a sibling entry.
{{code_ref: `taui/static/js/state.js`}}
## Apply boundary-aware arrow traversal in visible outline order

Use text-first arrows and traverse across entries only at text boundaries in visible outline order.

{{status: in-progress}}

- [specs/ui/keybindings.md#apply-boundary-aware-arrow-traversal-in-visible-outline-order](keybindings.md#apply-boundary-aware-arrow-traversal-in-visible-outline-order)

### Apply boundary-aware arrow traversal in visible outline order leaf
{{status: in-progress}}

- ArrowUp or ArrowDown moves across entries only when caret is at top or bottom boundary.
- Traversal skips collapsed descendants until they are explicitly revealed.
- Structural traversal commits pending edits before focus movement.
{{code_ref: `taui/static/js/state.js`}}
{{code_ref: `taui/static/js/state.js`}}
## Reserve pane and command shortcuts without conflicts

Reserve global shortcuts so they do not conflict with spec tree editing flow.

{{status: in-progress}}

- [specs/ui/keybindings.md#reserve-pane-and-command-shortcuts-without-conflicts](keybindings.md#reserve-pane-and-command-shortcuts-without-conflicts)

### Reserve pane and command shortcuts without conflicts leaf
{{status: in-progress}}

- Command and pane shortcuts remain available without overriding editing semantics.
{{code_ref: `taui/static/js/keys.js`}}
