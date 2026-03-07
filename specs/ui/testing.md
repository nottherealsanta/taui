# Testing

Define verification coverage for UI startup, reducer semantics, and key priority handling.

{{status: in-progress}}

- [specs/ui/testing.md#testing](testing.md#testing)
- [Verify startup smoke behavior](testing.md#verify-startup-smoke-behavior)
- [Verify reducer interaction semantics](testing.md#verify-reducer-interaction-semantics)
- [Verify key priority handling](testing.md#verify-key-priority-handling)

## Verify startup smoke behavior

Confirm app boot initializes selected spec reference and essential UI state.

{{status: in-progress}}

- [specs/ui/testing.md#verify-startup-smoke-behavior](testing.md#verify-startup-smoke-behavior)

### Verify startup smoke behavior leaf
{{status: in-progress}}

- Smoke test validates default selected entry and canonical `spec_ref` initialization.
{{code_ref: `taui/static/js/app.js`}}
## Verify reducer interaction semantics

Cover Enter, Shift+Enter, Tab, and boundary arrow behavior with persistence guarantees.

{{status: in-progress}}

- [specs/ui/testing.md#verify-reducer-interaction-semantics](testing.md#verify-reducer-interaction-semantics)

### Verify reducer interaction semantics leaf
{{status: in-progress}}

- Enter on non-empty text creates next editable entry in visible outline flow and focuses it.
- Shift+Enter inserts newline while preserving identity and depth.
- Tab nests under nearest valid previous sibling and keeps focus.
- ArrowUp and ArrowDown at text boundaries traverse to previous or next visible entry with persisted edits.
- Arrow traversal skips collapsed descendants until explicitly revealed.
- Structural transitions persist unsaved edits and always leave a visible caret target.
{{code_ref: `taui/static/js/state.js`}}
## Verify key priority handling

Verify transient UI precedence for Enter and arrows before text and structure handling.

{{status: in-progress}}

- [specs/ui/testing.md#verify-key-priority-handling](testing.md#verify-key-priority-handling)

### Verify key priority handling leaf
{{status: in-progress}}

- When transient UI is active, Enter and arrows resolve to transient handlers first.
{{code_ref: `taui/static/js/keys.js`}}
