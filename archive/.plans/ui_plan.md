# Taui UI Plan - Rust + GPUI

> Superseded on 2026-03-07 by the web UI migration (`uv run taui` + `taui/static/*`).

## 1. Prime Goal

Build a native Taui desktop UI in Rust using GPUI, with the spec tree as the primary user workflow and chat as a secondary escape hatch.

## 2. Scope

- Create a new `ui/` workspace for the desktop app.
- Implement a GPUI shell with four core panes:
  - spec tree
  - execution stream + Box inspector
  - plan/status view
  - chat/steering panel
- Integrate with Taui runtime over a local API/event stream.
- Keep UI behavior spec-driven so each action can map to a `spec_ref`.

## 3. Canonical Spec Contract (from main plan)

The UI must understand and enforce the spec tree contract defined in the main architecture plan.

### 3.1 `spec_ref` Format

Every executable task resolves to a canonical reference:

- `<spec_path>#<heading-anchor>`

Examples:

- `specs/_main.md#project-structure`
- `specs/agent/runtime.md#tool-execution`

### 3.2 Spec Node Schema

Each spec node includes:

- title
- one-line intent
- status: `draft | ready | in_progress | done | blocked`
- child index (non-leaf nodes)
- optional `depends_on` by `spec_ref`
- acceptance criteria (required for executable leaves)

Heading depth encodes tree depth (`#` = depth 1, `##` = depth 2, etc.).

### 3.3 Leaf Node Termination

A leaf terminates in exactly one of:

1. detailed implementation requirements (behavior, constraints, files, tests, acceptance)
2. explicit code anchors (`<file_path>:<line_range>`)

### 3.4 Traceability Requirement

Everything maps back to `spec_ref`: TaskGraph nodes, tool calls, file changes, verification evidence, clarifications, amendments, and Box acceptance/rejection.

### 3.5 Spec-Driven Verification

Verification is requirement-level, not only compile/lint-level:

```rust
struct SpecVerification {
    spec_ref: String,
    requirement: String,
    status: VerificationStatus, // Met | Unmet | Ambiguous
    evidence: String,
}
```

### 3.6 Clarification Gate

For blocking ambiguity, the UI must surface clarifications and block execution:

```rust
struct Clarification {
    spec_ref: String,
    question: String,
    options: Vec<String>,
    blocking: bool,
}
```

- No code writes for that node while blocking
- Node remains `blocked`
- Unresolved clarification persisted in session/spec metadata

### 3.7 Amendment Protocol

If implementation and spec conflict:

- Do not silently guess
- Generate amendment proposal
- Require explicit user approval before mutation
- UI renders amendment proposals inline with accept/reject controls

## 4. UI Folder Layout

- `ui/Cargo.toml`
- `ui/src/main.rs`
- `ui/src/app/mod.rs`
- `ui/src/app/state.rs`
- `ui/src/app/actions.rs`
- `ui/src/panes/spec_tree.rs`
- `ui/src/panes/execution.rs`
- `ui/src/panes/plan_status.rs`
- `ui/src/panes/chat.rs`
- `ui/src/services/backend_client.rs`
- `ui/src/services/event_stream.rs`
- `ui/src/services/spec_index.rs`
- `ui/src/theme/mod.rs`
- `ui/src/theme/colors.rs`
- `ui/src/theme/status_colors.rs`
- `ui/src/theme/syntax.rs`
- `ui/src/theme/registry.rs`
- `ui/tests/smoke.rs`
- `ui/skills/` (GPUI skill references)

## 5. Theme System (Zed-derived)

Taui adopts the Zed theme architecture, adapted for GPUI standalone use. Themes are structured as families containing one or more appearance variants (light/dark).

### 5.1 Architecture

```rust
struct ThemeFamily {
    name: String,
    author: String,
    themes: Vec<Theme>,
}

struct Theme {
    name: String,
    appearance: Appearance, // Light | Dark
    styles: ThemeStyles,
}

struct ThemeStyles {
    colors: ThemeColors,
    status: StatusColors,
    syntax: SyntaxTheme,
}
```

### 5.2 ThemeColors

Semantic color tokens organized by role. All colors are `Hsla`. This follows Zed's `ThemeColors` struct directly.

**Surface & Background:**
- `background` - app background and blank panels
- `surface_background` - grounded surfaces (panels, tabs)
- `elevated_surface_background` - elevated surfaces (menus, popups, dialogs)
- `panel_background`, `panel_focused_border`, `panel_overlay_background`
- `title_bar_background`, `title_bar_inactive_background`
- `status_bar_background`, `toolbar_background`
- `tab_bar_background`, `tab_active_background`, `tab_inactive_background`

**Border:**
- `border` - most borders, high contrast
- `border_variant` - deemphasized borders, visual dividers
- `border_focused` - focused elements
- `border_selected` - selected elements
- `border_transparent` - placeholder borders for state changes
- `border_disabled` - disabled elements

**Element (interactive components):**
- `element_background`, `element_hover`, `element_active`, `element_selected`, `element_disabled`
- `ghost_element_background`, `ghost_element_hover`, `ghost_element_active`, `ghost_element_selected`, `ghost_element_disabled`
- `drop_target_background`, `drop_target_border`

**Text & Icon:**
- `text`, `text_muted`, `text_placeholder`, `text_disabled`, `text_accent`
- `icon`, `icon_muted`, `icon_disabled`, `icon_placeholder`, `icon_accent`

**Scrollbar:**
- `scrollbar_thumb_background`, `scrollbar_thumb_hover_background`, `scrollbar_thumb_active_background`
- `scrollbar_thumb_border`, `scrollbar_track_background`, `scrollbar_track_border`

**Pane:**
- `pane_focused_border`, `pane_group_border`
- `panel_indent_guide`, `panel_indent_guide_hover`, `panel_indent_guide_active`

**Search:**
- `search_match_background`, `search_active_match_background`

**Links:**
- `link_text_hover`

### 5.3 StatusColors

Semantic status indicators with foreground/background/border triples:

- `error`, `error_background`, `error_border`
- `warning`, `warning_background`, `warning_border`
- `info`, `info_background`, `info_border`
- `success`, `success_background`, `success_border`
- `hint`, `hint_background`, `hint_border`
- `conflict`, `conflict_background`, `conflict_border`
- `created`, `created_background`, `created_border`
- `deleted`, `deleted_background`, `deleted_border`
- `modified`, `modified_background`, `modified_border`
- `renamed`, `renamed_background`, `renamed_border`
- `hidden`, `hidden_background`, `hidden_border`
- `ignored`, `ignored_background`, `ignored_border`

### 5.4 Taui-Specific Color Extensions

Beyond Zed's base tokens, Taui adds semantic colors for spec/agent workflows:

- `spec_draft`, `spec_ready`, `spec_in_progress`, `spec_done`, `spec_blocked` - node status indicators
- `agent_root`, `agent_minion` - agent hierarchy indicators
- `box_completed`, `box_failed`, `box_partial`, `box_halted` - Box status colors
- `clarification_blocking`, `clarification_non_blocking` - clarification urgency
- `amendment_proposed`, `amendment_accepted`, `amendment_rejected` - amendment state
- `verification_met`, `verification_unmet`, `verification_ambiguous` - requirement compliance

### 5.5 SyntaxTheme

Syntax highlighting colors follow Zed's model - a map of scope names to highlight styles:

```rust
struct SyntaxTheme {
    highlights: Vec<(String, HighlightStyle)>,
}

struct HighlightStyle {
    color: Option<Hsla>,
    background_color: Option<Hsla>,
    font_style: Option<FontStyle>,
    font_weight: Option<FontWeight>,
}
```

### 5.6 Theme Access Pattern

Themes are accessed via GPUI's global context:

```rust
// Access from any render context
let colors = cx.theme().colors();
div()
    .bg(colors.background)
    .text_color(colors.text)
    .border_color(colors.border)
```

### 5.7 Theme Refinement

Themes support partial overrides via a `Refinement` pattern (matching Zed's `Refineable` derive):

```rust
// User overrides only the fields they care about
let overrides = ThemeColorsRefinement {
    text: Some(hsla(0.0, 0.0, 0.95, 1.0)),
    background: Some(hsla(0.0, 0.0, 0.02, 1.0)),
    ..Default::default()
};
colors.refine(&overrides);
```

### 5.8 Bundled Themes

Ship with at least:

- Taui Dark (default) - a dark theme designed for the spec-first workflow
- Taui Light - light variant
- Zed One Dark (ported) - familiar to Zed users

User themes loadable from `~/.config/taui/themes/*.json` following the `ThemeFamilyContent` JSON schema.

## 6. Spec Tree for UI Work

### 6.1 `ui/specs/_main.md` (root)

- Intent: overall UI architecture and milestone tracking.
- Children:
  - `app_shell.md`
  - `state_and_events.md`
  - `spec_tree_pane.md`
  - `execution_pane.md`
  - `plan_status_pane.md`
  - `chat_pane.md`
  - `theme.md`
  - `backend_integration.md`
  - `keybindings.md`
  - `spec_tree_interaction.md`
  - `testing.md`

### 6.2 `ui/specs/app_shell.md`

- Files:
  - `ui/src/main.rs`
  - `ui/src/app/mod.rs`
- Requirements:
  - bootstrap GPUI app
  - create docked 4-pane workspace
  - persist and restore last layout/session
- Leaf functions/structs:
  - `fn main()`
  - `fn build_app(cx: &mut AppContext) -> AppShell`
  - `struct AppShell`

### 6.3 `ui/specs/state_and_events.md`

- Files:
  - `ui/src/app/state.rs`
  - `ui/src/app/actions.rs`
- Requirements:
  - central app state for current workspace, selected `spec_ref`, active run, and filter toggles
  - typed action/event model for pane communication
  - state management via GPUI `Model<AppState>` with `cx.observe()` for reactivity
  - maintain spec-tree editor session state:
    - active node identity and `spec_ref`
    - caret position
    - pending edits
    - mode (`editing|selection`)
    - navigation direction/context for boundary transitions
  - provide deterministic visible-outline traversal contract for spec tree editing:
    - `resolve_prev_visible_editable_node(...)`
    - `resolve_next_visible_editable_node(...)`
  - enforce commit boundaries before structural transitions (node switch, create/split, indent, exit edit mode)
- Leaf functions/structs:
  - `struct AppState`
  - `struct SpecTreeEditorSession`
  - `enum UiAction`
  - `enum EditorMode`
  - `fn dispatch(state: &mut AppState, action: UiAction, cx: &mut ModelContext<AppState>)`

### 6.4 `ui/specs/spec_tree_pane.md`

- Files:
  - `ui/src/panes/spec_tree.rs`
  - `ui/src/services/spec_index.rs`
- Requirements:
  - render expandable spec tree from markdown metadata, respecting heading-depth = tree-depth
  - show node status badges (`draft|ready|in_progress|done|blocked`) using spec status colors
  - show `depends_on` edges and blocked-by indicators
  - open node details: intent, acceptance criteria, child index
  - emit selected `spec_ref` in canonical `<spec_path>#<heading-anchor>` format
  - surface inline clarifications (blocking shown with `clarification_blocking` color)
  - surface amendment proposals with accept/reject controls
- Leaf functions/structs:
  - `struct SpecTreePane`
  - `fn render_tree(...)`
  - `fn select_spec_ref(...)`
  - `fn render_node_status(...)`
  - `fn render_clarification(...)`
  - `fn render_amendment(...)`

### 6.5 `ui/specs/execution_pane.md`

- Files:
  - `ui/src/panes/execution.rs`
  - `ui/src/services/event_stream.rs`
- Requirements:
  - stream `AgentEvent` timeline in order
  - show per-task status and evidence links, with `spec_ref` lineage
  - inspect Box payloads: summary, diffs, `SpecVerification` results, proposed amendments
  - accept/reject Box results with requirement-level compliance display
  - color-code Box status (`box_completed`, `box_failed`, `box_partial`, `box_halted`)
- Leaf functions/structs:
  - `struct ExecutionPane`
  - `fn bind_event_stream(...)`
  - `fn render_box_inspector(...)`
  - `fn render_spec_compliance(...)`

### 6.6 `ui/specs/plan_status_pane.md`

- Files:
  - `ui/src/panes/plan_status.rs`
- Requirements:
  - display TaskGraph as a DAG visualization with dependency edges
  - show queued/running/completed/failed tasks
  - show tier assignment per task (`junior|mid|senior`)
  - show `spec_ref` lineage for each task node
  - show file ownership per task and flag conflicts
  - update live as scheduler progresses
- Leaf functions/structs:
  - `struct PlanStatusPane`
  - `fn render_task_graph(...)`
  - `fn render_task_node(...)`
  - `fn highlight_active_wave(...)`

### 6.7 `ui/specs/chat_pane.md`

- Files:
  - `ui/src/panes/chat.rs`
- Requirements:
  - send steering messages to root/minion target
  - show queued/running status while tools execute
  - keep chat secondary to spec-driven actions
  - default target is root agent; optional direct target by minion ID
  - messages queue and apply on next think cycle
- Leaf functions/structs:
  - `struct ChatPane`
  - `fn submit_message(...)`
  - `fn set_target_agent(...)`

### 6.8 `ui/specs/theme.md`

- Files:
  - `ui/src/theme/mod.rs`
  - `ui/src/theme/colors.rs`
  - `ui/src/theme/status_colors.rs`
  - `ui/src/theme/syntax.rs`
  - `ui/src/theme/registry.rs`
- Requirements:
  - implement `ThemeColors`, `StatusColors`, `SyntaxTheme` structs following Zed model
  - add Taui-specific color extensions (spec status, agent, Box, verification)
  - theme registry with bundled themes + user theme loading from `~/.config/taui/themes/`
  - `ThemeColorsRefinement` support for partial user overrides
  - `cx.theme()` global access pattern
  - dark mode as default
- Leaf functions/structs:
  - `struct ThemeColors`
  - `struct StatusColors`
  - `struct SyntaxTheme`
  - `struct ThemeRegistry`
  - `fn load_bundled_themes() -> Vec<ThemeFamily>`
  - `fn load_user_themes(path: &Path) -> Vec<ThemeFamily>`

### 6.9 `ui/specs/backend_integration.md`

- Files:
  - `ui/src/services/backend_client.rs`
  - `ui/src/services/event_stream.rs`
- Requirements:
  - request plan/execution operations by `spec_ref`
  - reconnect stream with backoff
  - map backend errors into user-facing diagnostics
- Leaf functions/structs:
  - `struct BackendClient`
  - `fn start_run(spec_ref: &str) -> Result<RunId>`
  - `fn subscribe_events(run_id: RunId) -> impl Stream<Item = AgentEvent>`

### 6.10 `ui/specs/keybindings.md`

- Files:
  - `ui/src/app/keybindings.rs`
- Requirements:
  - keyboard-first navigation for spec tree (up/down/expand/collapse/select) with explicit behavior contracts
  - key resolution priority order:
    - transient UI handlers (autocomplete, slash command menus, inline pickers)
    - editor text handlers
    - structural outline handlers
  - Enter/Shift+Enter/Tab contracts:
    - Enter performs structural create/split by default (not inline newline)
    - Shift+Enter inserts newline within current node text
    - Tab indents current node under nearest valid previous sibling
  - Arrow contracts:
    - ArrowUp/ArrowDown are text-first and cross-node only at top/bottom boundaries
    - cross-node movement uses visible outline order and skips hidden descendants under collapsed parents
    - ArrowLeft/ArrowRight stay text-first; at absolute boundaries they may transition editor state but must not create/delete nodes
  - command palette (`cmd+shift+p`) for all actions
  - pane focus cycling (`cmd+1..4`)
  - quick `spec_ref` jump (`cmd+p` fuzzy finder)
  - accept/reject shortcuts for Boxes and amendments
- Leaf functions/structs:
  - `fn register_keybindings(cx: &mut AppContext)`
  - `struct CommandPalette`

### 6.11 `ui/specs/spec_tree_interaction.md`

- Files:
  - `ui/src/panes/spec_tree.rs`
  - `ui/src/app/state.rs`
  - `ui/src/app/keybindings.rs`
- Requirements:
  - define interaction terminology for spec tree editor:
    - node/block, editing mode, selection mode, sibling, child, visible outline order
  - entering edit mode:
    - trigger via click, keyboard navigation landing, or structural create/split actions
    - initialize editor session with active node, context, caret position, and direction when relevant
  - save and exit boundaries:
    - persist/reconcile edits when focus changes, edit mode exits, structural action occurs, or command requires persisted content
    - prevent silent edit loss during any structural transition
  - Enter semantics (structural):
    - finalize current node content
    - create next editable node in outline flow (usually next sibling; split behavior allowed when caret is mid-text)
    - move focus and caret into the new node
  - child semantics:
    - Tab indents current node into child position under nearest valid previous sibling
    - creating a child that would be hidden by collapse must auto-expand parent or otherwise reveal insertion deterministically
  - Shift+Enter semantics (text):
    - insert newline in current node
    - preserve node identity and tree depth
  - Arrow semantics:
    - ArrowUp/ArrowDown move within text first; at top/bottom boundaries they commit edits and move to previous/next visible editable node
    - ArrowLeft/ArrowRight remain text-first and only participate in boundary-aware editor state transitions
  - transient UI precedence:
    - while autocomplete/command menus/pickers are active, Enter and arrows are handled by the transient UI before editor/structure rules
  - focus and persistence guarantees:
    - deterministic target resolution
    - visible caret after movement
    - outline consistency preserved across navigation and structural edits
- Leaf functions/structs:
  - `enum EditorMode`
  - `enum NavigationDirection`
  - `fn enter_edit_mode(...)`
  - `fn commit_active_node_if_dirty(...)`
  - `fn handle_enter(...)`
  - `fn handle_shift_enter(...)`
  - `fn handle_tab_indent(...)`
  - `fn handle_arrow_navigation(...)`
  - `fn resolve_next_visible_editable_node(...)`
  - `fn resolve_prev_visible_editable_node(...)`

### 6.12 `ui/specs/testing.md`

- Files:
  - `ui/tests/smoke.rs`
  - `ui/tests/state_reducer.rs`
- Requirements:
  - smoke boot test for app startup
  - state dispatch tests for action/state transitions
  - service tests for stream reconnect and decoding
  - theme loading tests

## 7. Milestones

1. **Bootstrap** - Rust crate + GPUI app shell + theme system.
2. **Pane scaffolding** - shared state/actions, all four panes rendered (empty).
3. **Spec tree** - spec index, tree rendering, `spec_ref` selection, status display.
4. **Backend integration** - API client, event stream, reconnect logic.
5. **Execution + plan** - Box inspector, TaskGraph visualization, live updates.
6. **Steering + keybindings** - chat panel, command palette, keyboard navigation, and outline interaction semantics parity with behavior-level keyboard UX verification.
7. **Verification UX** - clarification gate, amendment flow, compliance display.
8. **Tests + polish** - smoke tests, state tests, service tests, theme polish.

Dependency notes: milestones 1-2 are sequential. Milestones 3 and 4 can overlap. Milestones 5-7 depend on both 3 and 4. Milestone 8 runs continuously from milestone 3 onward.

## 8. Acceptance Criteria

- UI launches from `ui/` with one command (`cargo run`).
- Selecting a node yields canonical `spec_ref` in `<spec_path>#<heading-anchor>` format.
- Spec tree shows node status, dependencies, clarifications, and amendments.
- Executions stream live status/evidence without UI freeze.
- Box inspector shows requirement-level `SpecVerification` results.
- TaskGraph pane shows DAG with dependency edges and live task status.
- User can send steering messages to root or targeted minion.
- Theme system loads bundled + user themes, supports refinement overrides.
- All panes navigable via keyboard; command palette provides action discovery.
- Enter on a non-empty spec node creates the next editable node in outline flow and focuses it.
- Shift+Enter inserts a newline in the same node without changing node identity or depth.
- Tab indents the current node under the nearest valid previous sibling and keeps focus on the moved node.
- ArrowUp/ArrowDown at node boundaries persist pending edits and move to previous/next visible editable node.
- Arrow traversal skips hidden descendants of collapsed parents unless revealed.
- While transient UI is active (autocomplete/menu/picker), Enter and arrows are consumed by transient UI handlers first.
- Structural transitions guarantee no silent edit loss and always end with a deterministic, visible caret target.
- Core flows are covered by smoke + state/service/theme tests.
