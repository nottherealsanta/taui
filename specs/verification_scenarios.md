# Verification Scenarios

Define verification leaves that map directly to this repository's current tests.

{{status: ready}}

- [specs/verification_scenarios.md#verification-scenarios](verification_scenarios.md#verification-scenarios)
- [Verify Enter creates and focuses new node](verification_scenarios.md#verify-enter-creates-and-focuses-new-node)
- [Verify Shift+Enter preserves identity and depth](verification_scenarios.md#verify-shiftenter-preserves-identity-and-depth)
- [Verify Tab indent reveals collapsed parent](verification_scenarios.md#verify-tab-indent-reveals-collapsed-parent)
- [Verify transient key priority classification](verification_scenarios.md#verify-transient-key-priority-classification)

## Verify Enter creates and focuses new node

Confirm structural Enter behavior creates exactly one node and focuses it in editing mode.

{{status: ready}}

- [specs/verification_scenarios.md#verify-enter-creates-and-focuses-new-node](verification_scenarios.md#verify-enter-creates-and-focuses-new-node)

### Verify Enter creates and focuses new node leaf
{{status: ready}}

- Reducer test passes with node count increment and caret at zero.
{{code_ref: `taui/static/js/state.js`}}
## Verify Shift+Enter preserves identity and depth

Confirm newline insertion does not change selected node identity or depth.

{{status: ready}}

- [specs/verification_scenarios.md#verify-shiftenter-preserves-identity-and-depth](verification_scenarios.md#verify-shiftenter-preserves-identity-and-depth)

### Verify Shift+Enter preserves identity and depth leaf
{{status: ready}}

- Reducer test passes with unchanged node id and depth.
{{code_ref: `taui/static/js/state.js`}}
## Verify Tab indent reveals collapsed parent

Confirm indenting under a collapsed parent auto-expands that parent.

{{status: ready}}

- [specs/verification_scenarios.md#verify-tab-indent-reveals-collapsed-parent](verification_scenarios.md#verify-tab-indent-reveals-collapsed-parent)

### Verify Tab indent reveals collapsed parent leaf
{{status: ready}}

- Reducer test passes with target parent collapsed flag set to false.
{{code_ref: `taui/static/js/state.js`}}
## Verify transient key priority classification

Confirm Enter and arrows are classified as transient-priority keys while Tab/Escape are excluded.

{{status: ready}}

- [specs/verification_scenarios.md#verify-transient-key-priority-classification](verification_scenarios.md#verify-transient-key-priority-classification)

### Verify transient key priority classification leaf
{{status: ready}}

- Keybinding priority test passes with expected key membership.
{{code_ref: `taui/static/js/keys.js`}}
