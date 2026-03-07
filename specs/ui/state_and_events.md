# State and Events

Define reducer state and event contracts for editing sessions and structure traversal.

{{status: in-progress}}

- [specs/ui/state_and_events.md#state-and-events](state_and_events.md#state-and-events)
- [Track app state for selection and spec references](state_and_events.md#track-app-state-for-selection-and-spec-references)
- [Track editor session state for traversal context](state_and_events.md#track-editor-session-state-for-traversal-context)
- [Resolve deterministic visible traversal targets](state_and_events.md#resolve-deterministic-visible-traversal-targets)
- [Commit pending edits before structure transitions](state_and_events.md#commit-pending-edits-before-structure-transitions)
- [Dispatch typed actions through reducer](state_and_events.md#dispatch-typed-actions-through-reducer)

## Track app state for selection and spec references

Store outline data, current selection, canonical spec reference, and chat draft.

{{status: in-progress}}

- [specs/ui/state_and_events.md#track-app-state-for-selection-and-spec-references](state_and_events.md#track-app-state-for-selection-and-spec-references)

### Track app state for selection and spec references leaf
{{status: in-progress}}

- Selection updates keep canonical `spec_ref` synchronized with current heading target.
{{code_ref: `taui/static/js/state.js`}}
## Track editor session state for traversal context

Track active entry id, caret position, pending edits, mode, and traversal context.

{{status: in-progress}}

- [specs/ui/state_and_events.md#track-editor-session-state-for-traversal-context](state_and_events.md#track-editor-session-state-for-traversal-context)

### Track editor session state for traversal context leaf
{{status: in-progress}}

- Editor session state includes active entry id, caret offset, pending edits, mode, and traversal direction context.
{{code_ref: `taui/static/js/state.js`}}
## Resolve deterministic visible traversal targets

Resolve previous and next visible editable entry in deterministic outline order.

{{status: in-progress}}

- [specs/ui/state_and_events.md#resolve-deterministic-visible-traversal-targets](state_and_events.md#resolve-deterministic-visible-traversal-targets)

### Resolve deterministic visible traversal targets leaf
{{status: in-progress}}

- Hidden descendants under collapsed parents are excluded from traversal target resolution.
{{code_ref: `taui/static/js/state.js`}}
## Commit pending edits before structure transitions

Persist pending text before selection moves or hierarchy mutations.

{{status: in-progress}}

- [specs/ui/state_and_events.md#commit-pending-edits-before-structure-transitions](state_and_events.md#commit-pending-edits-before-structure-transitions)

### Commit pending edits before structure transitions leaf
{{status: in-progress}}

- Select, split, depth change, and boundary traversal flows persist pending edits before transition.
{{code_ref: `taui/static/js/state.js`}}
## Dispatch typed actions through reducer

Use typed `UiAction` events for editing, selection, traversal, and hierarchy updates.

{{status: in-progress}}

- [specs/ui/state_and_events.md#dispatch-typed-actions-through-reducer](state_and_events.md#dispatch-typed-actions-through-reducer)

### Dispatch typed actions through reducer leaf
{{status: in-progress}}

- Reducer transitions remain deterministic for identical action sequences.
{{code_ref: `taui/static/js/state.js`}}
