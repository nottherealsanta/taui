# Migration Plan: GPUI → Tauri + Vite + Svelte 5

> Supersedes the Rust + GPUI UI in `ui/` (archived).
> Companion to `single-pane-tree-plan.md` for UX direction.

## 1. Overview

Replace the native Rust/GPUI desktop UI (`ui/` directory) with a **Tauri v2** application using **Vite** as the build tool and **Svelte 5** (with runes) as the frontend framework. Custom components built with **Tailwind CSS** only — no component library.

**Directory structure after migration:**

```
taui/
├── app/                          # NEW – Tauri + Svelte application
│   ├── src/                      # Svelte frontend source
│   ├── src-tauri/                # Tauri Rust backend
│   ├── package.json
│   ├── vite.config.ts
│   ├── svelte.config.js
│   └── tailwind.config.ts
├── taui/                         # Existing Python backend (unchanged)
├── specs/                        # Spec tree (unchanged)
├── .plans/                       # Plans (unchanged)
└── AGENTS.md
```

The existing `ui/` directory (Rust/GPUI) will be archived and removed.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────┐
│                  Tauri Shell (v2)                 │
│  ┌────────────────────────────────────────────┐  │
│  │            Svelte 5 + Vite Frontend        │  │
│  │                                            │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │         Single-Pane Tree View        │  │  │
│  │  │  (spec tree, inline editing, fold)   │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │     Bottom Drawer (Code | Terminal)   │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │  Agent Detail Panel (slide-in right) │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │        Message Bar (bottom)          │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────┘  │
│                       │                          │
│           Direct WebSocket (JSON-RPC 2.0)        │
│                       │                          │
│           Tauri IPC for native features only     │
│           (window management, menus, fs)          │
└───────────────────────┼──────────────────────────┘
                        │
            ┌───────────┴───────────┐
            │  Python FastAPI       │
            │  (ws://127.0.0.1:     │
            │         8000/ws)      │
            └───────────────────────┘
```

**Communication model:**

- Svelte connects directly to the Python backend via WebSocket (same JSON-RPC 2.0 protocol as today).
- Tauri provides: native window chrome, titlebar, menus, file system access, system tray.
- Tauri IPC used only for native features the browser sandbox cannot provide.

---

## 3. Phased Implementation

### ~~Phase 1: Scaffold and Bootstrap~~ ✅ DONE

### Phase 1: Scaffold and Bootstrap

**Goal:** Get a blank Tauri + Vite + Svelte 5 app running with Tailwind CSS.

| Task | Details |
|------|---------|
| **1.1** Initialize Tauri v2 project | `npm create tauri-app@latest app -- --template svelte-ts` in repo root. Produces `app/` with `src-tauri/` and `src/`. |
| **1.2** Configure Vite | `vite.config.ts` with `@sveltejs/vite-plugin-svelte`, path aliases (`$lib`, `$components`, etc.). |
| **1.3** Set up Tailwind CSS v4 | Install `@tailwindcss/vite`, configure `app.css` with `@import "tailwindcss"`, define design tokens (colors from existing `theme/colors.rs`). |
| **1.4** Configure Tauri | `tauri.conf.json`: window title "Taui", default size, titlebar hidden (custom titlebar), CSP allowing WebSocket to `ws://127.0.0.1:8000`. |
| **1.5** Set up TypeScript | Strict mode, path aliases matching Vite, type definitions for JSON-RPC messages. |
| **1.6** Install key dependencies | `@milkdown/core` + `@milkdown/preset-commonmark` (markdown editor), `monaco-editor` (code viewer/editor), `@xterm/xterm` (terminal), fonts (IBM Plex Sans, JetBrains Mono via `@fontsource`). |
| **1.7** Verify dev loop | `npm run tauri dev` opens a native window with a placeholder Svelte page. |

**Files created:**

```
app/
├── src/
│   ├── app.css                   # Tailwind + design tokens
│   ├── App.svelte                # Root component
│   ├── main.ts                   # Svelte mount point
│   └── vite-env.d.ts
├── src-tauri/
│   ├── src/main.rs               # Tauri entry
│   ├── Cargo.toml
│   └── tauri.conf.json
├── index.html
├── package.json
├── vite.config.ts
├── svelte.config.js
├── tailwind.config.ts
└── tsconfig.json
```

---

### ~~Phase 2: State Management and Backend Client~~ ✅ DONE

### ~~Phase 3: Theme System~~ ✅ DONE

### ~~Phase 4: Core UI Components (Custom, Tailwind-only)~~ ✅ DONE

### ~~Phase 5: Spec Tree Pane (Primary View)~~ ✅ DONE (see below)

### Phase 5: Spec Tree Pane (Primary View)

**Goal:** Port the core state layer and WebSocket client from Rust to TypeScript/Svelte.

| Task | Details |
|------|---------|
| **2.1** Define TypeScript types | Port all types from `state.rs`: `SpecNode`, `AppState`, `AgentState`, `AgentTier`, `AgentInfo`, `PendingQuestion`, `AgentDetailEvent`, `EditorMode`, `FlatNode`, `BackendState`, `MetadataEditTarget`. |
| **2.2** Create WebSocket client | Port `backend_client.rs` → `$lib/services/backend-client.ts`. JSON-RPC 2.0 request/response/notification handling, auto-reconnect with exponential backoff (250ms → 30s), `TAUI_BACKEND_WS` env var support. |
| **2.3** Create app store | `$lib/stores/app-state.svelte.ts` using Svelte 5 `$state` runes. Single reactive `AppState` object. Port `hydrate_from_backend`, `flattened_nodes`, `set_selected`, `toggle_collapse`. |
| **2.4** Create action dispatcher | Port `actions.rs` → `$lib/stores/actions.ts`. Same `UiAction` enum + `dispatch()` function operating on the app state. |
| **2.5** Wire notification handlers | Map all `ServerNotification` variants (`spec/nodeChanged`, `agent/stateChanged`, etc.) to state mutations. |
| **2.6** Create connection manager | Svelte module that initializes connection on app mount, calls `initialize` + `spec/getTreeDetailed`, populates state, starts notification listener. |

**Key mapping from Rust → TypeScript:**

| Rust (`state.rs`) | TypeScript |
|---|---|
| `pub type NodeId = usize` | `type NodeId = number` |
| `pub type SpecRef = String` | `type SpecRef = string` |
| `pub struct SpecNode { ... }` | `interface SpecNode { ... }` |
| `pub struct AppState { ... }` | `class AppState { ... }` with `$state` fields |
| `pub fn dispatch(state, action)` | `function dispatch(state: AppState, action: UiAction): boolean` |
| `Entity<InputState>` | `$state()` reactive variable |
| `cx.notify()` | Automatic Svelte reactivity |

---

### Phase 3: Theme System

**Goal:** Port the Zed-derived semantic theme from Rust to CSS/Tailwind.

| Task | Details |
|------|---------|
| **3.1** Define CSS custom properties | Port `colors.rs` → CSS variables in `app.css`. Semantic tokens: `--bg-base`, `--bg-surface`, `--fg-primary`, `--border-default`, etc. |
| **3.2** Port status colors | Port `status_colors.rs` → CSS variables for spec status (`--status-draft`, `--status-ready`, `--status-in-progress`, `--status-done`, `--status-blocked`) and agent states. |
| **3.3** Create theme switcher | `$lib/stores/theme.svelte.ts` with `$state` for active theme. Support dark/light toggle. Persist in `localStorage`. |
| **3.4** Extend Tailwind | Custom colors in `tailwind.config.ts` referencing CSS variables, so you can use `bg-surface`, `text-primary`, `border-default`, etc. |
| **3.5** Typography constants | Port `typography.rs` constants: `BODY_FONT_FAMILY`, `CODE_FONT_FAMILY`, `INDENT_PER_LEVEL`, `MARKDOWN_TEXT_SIZE`, `MARKDOWN_LINE_HEIGHT`, `MAX_CONTENT_WIDTH`. |
| **3.6** Monaco theme | Create a custom Monaco theme that matches Taui's semantic tokens (dark/light variants). Register via `monaco.editor.defineTheme()`. Map Taui's existing syntax highlight tokens from `syntax.rs` to Monaco's `tokenColors`. |

---

### Phase 4: Core UI Components (Custom, Tailwind-only)

**Goal:** Build the foundational custom components needed for the tree UI.

| Component | Purpose | Key behavior |
|-----------|---------|--------------|
| **4.1** `TitleBar.svelte` | Custom draggable titlebar | Tauri `data-tauri-drag-region`, window controls (min/max/close via Tauri API), root node title display. |
| **4.2** `TreeRow.svelte` | Single spec tree row | Depth-based indentation (`INDENT_PER_LEVEL`), chevron toggle, status badge, agent indicator dot, lock icon, selection highlight, click-to-select. |
| **4.3** `TreeView.svelte` | Virtualized tree list | Renders `FlatNode[]`, keyboard navigation (up/down/tab/shift-tab/enter/escape), scroll into view for selected node. |
| **4.4** `InlineEditor.svelte` | Markdown editing for active node | Milkdown integration, save on blur/node-switch, discard on Escape, Enter for structural add-sibling. |
| **4.5** `MessageBar.svelte` | Bottom input bar | Agent launch (tier selector), steer/queue messages, tool brief display. |
| **4.6** `AgentDetailPanel.svelte` | Slide-in right panel | Agent event stream (messages, tool calls, tool results, tokens), subscribe/unsubscribe lifecycle. |
| **4.7** `MetadataRow.svelte` | Code refs, verification, depends_on, related_to | Inline editing, expandable code previews. |
| **4.8** `QuestionOverlay.svelte` | Agent question on node | Options as buttons, text input for custom answer. |
| **4.9** `BottomDrawer.svelte` | Collapsible drawer with tabs | Code tab (Monaco editor, read-only), Terminal tab (xterm). |
| **4.10** `StatusBadge.svelte` | Spec node status indicator | Colored dot/text for draft/ready/in-progress/done/blocked. |
| **4.11** `MonacoEditor.svelte` | Reusable Monaco wrapper | Svelte component wrapping `monaco-editor`. Accepts `value`, `language`, `readOnly`, `theme` props. Handles lifecycle (create/dispose), resize observer, and theme switching. |

---

### ~~Phase 5: Spec Tree Pane (Primary View)~~ ✅ DONE

| Task | Details |
|------|---------|
| **5.1** Tree rendering | `TreeView` consuming `flattened_nodes()` from app state. Depth indentation, collapse/expand chevrons. |
| **5.2** Selection and navigation | Arrow keys for up/down, click to select. Selection mode (blue highlight) vs editing mode (cursor in editor). |
| **5.3** Inline editing | When a node enters editing mode: mount Milkdown editor with node's markdown. F2 or double-click to enter edit mode. Escape to exit. Blur saves via `spec/updateNode` RPC. |
| **5.4** Structural editing | Enter: `spec/createSiblingNode`. Tab: `spec/indentNode`. Shift+Tab: `spec/outdentNode`. All synced to backend. |
| **5.5** Fold/unfold | Chevron click or keyboard shortcut toggles collapse. Fold state persisted in `localStorage` keyed by `spec_ref`. |
| **5.6** Code ref previews | Click code_ref metadata → fetch via `spec/getNodeCodeRefs` → display in Monaco in bottom drawer's Code tab with correct language mode. |
| **5.7** Agent indicators | Colored dot on nodes with active agents. Lock icon on locked branches. Question overlay for pending questions. |
| **5.8** Scroll behavior | Auto-scroll to keep selected node visible. Smooth scrolling. Virtual scrolling for large trees (consider `svelte-virtual-list` or custom implementation). |

---

### ~~Phase 6: Bottom Drawer (Code + Terminal)~~ ✅ DONE

**Goal:** Implement the collapsible bottom drawer with Code and Terminal tabs per `single-pane-tree-plan.md`.

| Task | Details |
|------|---------|
| **6.1** Drawer shell | Resizable (drag handle), collapsible, tab bar with "Code" and "Terminal". |
| **6.2** Code tab — Monaco | Full Monaco editor instance in read-only mode. Syntax highlighting auto-detected from file extension. Minimap enabled for large files. 10-line default preview height, expand/collapse toggle to show full range. Line number gutter showing real file line numbers (via `lineNumbers` config starting from `line_start`). Click-to-expand toggles between preview (10 lines) and full content. |
| **6.3** Terminal tab | xterm.js integration. Command input + Run/Stop controls. Stream `run/output` notifications. Handle `run/completed`. |
| **6.4** Backend integration | Wire `spec/getNodeSourceRange` RPC. Wire `run/start`, `run/status`, `run/stop` RPCs and their notifications. |

**Monaco configuration for code preview:**

```typescript
// Code tab Monaco options
{
  readOnly: true,
  minimap: { enabled: true },
  scrollBeyondLastLine: false,
  lineNumbers: (n) => String(n + lineStart - 1),  // show real file line numbers
  wordWrap: 'on',
  folding: true,
  renderLineHighlight: 'none',
  theme: 'taui-dark',  // custom theme matching Taui tokens
  automaticLayout: true,  // respond to container resize
}
```

---

### ~~Phase 7: Agent Integration~~ ✅ DONE

**Goal:** Full agent lifecycle UI matching what exists in the GPUI version.

| Task | Details |
|------|---------|
| **7.1** Agent launch | Tier selector (junior/mid/senior) in message bar. `agent/launch` RPC with selected `spec_ref`. |
| **7.2** Agent state tracking | `agent/stateChanged` notifications → update `AgentInfo` in state. Visual indicators: Running/Thinking/ToolExecution/AskingQuestion/Done. |
| **7.3** Agent detail panel | Slide-in panel showing event stream. `agent/subscribe`/`agent/unsubscribe` on open/close. Render `AgentDetailEvent` variants (messages, tool calls, results, tokens). |
| **7.4** Agent detail — Monaco diffs | When an agent produces file diffs (in `ToolResult`), render them with Monaco's diff editor (`monaco.editor.createDiffEditor`). This gives syntax-highlighted inline or side-by-side diff views for code changes. |
| **7.5** Steering and queuing | `agent/steer` for immediate context. `agent/queue` for follow-up. Both via message bar. |
| **7.6** Questions | `agent/questionAsked` → overlay on relevant node. `agent/answerQuestion` RPC on user response. |
| **7.7** Tool briefs | `agent/toolBrief` → ephemeral display above message bar. |
| **7.8** Lock display | `agent/lockChanged` → visual lock on affected branches. |

---

### ~~Phase 8: Keybindings and Polish~~ ✅ DONE

**Goal:** Port all keyboard shortcuts and finalize UX.

| Task | Details |
|------|---------|
| **8.1** Port keybindings | Map from `keybindings.rs`: ArrowDown/Up → SelectNext/Prev, Tab/Shift+Tab → Indent/Outdent, Enter → AddSibling (in selection mode), F2 → Enter editing, Escape → Exit editing. |
| **8.2** Command palette | `Cmd+Shift+P` (macOS) / `Ctrl+Shift+P` (other): fuzzy search over all actions. Consider reusing Monaco's built-in command palette API (`editor.trigger('', 'editor.action.quickCommand')`) for consistency if desired. |
| **8.3** Quick jump | `Cmd+P` / `Ctrl+P`: fuzzy finder for `spec_ref` navigation. |
| **8.4** Focus management | Proper focus trap in editing mode, focus ring styles, tab order. When Monaco is focused, let it handle its own keybindings; intercept only at the app shell level when Monaco is not focused. |
| **8.5** Window title | Dynamic title showing root node name + connection status. |
| **8.6** Native menus | Tauri menu API: File, Edit, View menus with standard shortcuts. |
| **8.7** Error handling | Connection error banner, reconnection indicator, RPC error toasts. |

---

### ~~Phase 9: Testing~~ ✅ DONE

**Goal:** Port existing tests and add web-specific tests.

| Task | Details |
|------|---------|
| **9.1** Unit tests for state | Port `tests/state_reducer.rs` (415 lines) → Vitest. Test all `dispatch()` actions, `hydrate_from_backend`, `flattened_nodes`, collapse/expand. |
| **9.2** Unit tests for typography | Port typography parsing tests → Vitest. |
| **9.3** WebSocket client tests | Mock WebSocket, test JSON-RPC request/response, reconnection, notification routing. |
| **9.4** Component tests | `@testing-library/svelte` for TreeRow, TreeView, InlineEditor, MessageBar, MonacoEditor. |
| **9.5** E2E tests | Playwright or WebdriverIO with Tauri driver for full flow: connect → tree load → select → edit → save. |

---

### Phase 10: Archive and Cleanup

| Task | Details |
|------|---------|
| **10.1** Archive `ui/` | Git tag `gpui-archive`, then remove `ui/` directory from active codebase. |
| **10.2** Update specs | Update `ui/specs/_main.md` and child specs to reflect new architecture (or move specs to `app/specs/`). |
| **10.3** Update AGENTS.md | Document new dev setup: `cd app && npm install && npm run tauri dev`. |
| **10.4** Update `.plans/ui_plan.md` | Mark fully superseded, reference this new plan. |
| **10.5** CI/CD | Add GitHub Actions for `npm run build`, `npm run tauri build`, `vitest run`. |

---

## 4. Monaco Editor Integration Details

Monaco is used in three distinct contexts across the application:

### 4a. Code Preview (Bottom Drawer — Code Tab)

- **Mode:** Read-only.
- **Purpose:** Display code referenced by `code_refs` metadata on spec nodes.
- **Behavior:** User clicks a code ref → `spec/getNodeCodeRefs` RPC returns file content with line range → Monaco displays with correct language mode (inferred from file extension), real line numbers, and 10-line collapsed preview that can expand.
- **Key config:** `readOnly: true`, `minimap: { enabled: true }`, `scrollBeyondLastLine: false`, custom line number offset.

### 4b. Agent Diff Viewer (Agent Detail Panel)

- **Mode:** Monaco Diff Editor.
- **Purpose:** Show file changes produced by agent tool calls (e.g., file edits).
- **Behavior:** When an `AgentDetailEvent.ToolResult` contains a diff or before/after content, render via `monaco.editor.createDiffEditor()` with inline or side-by-side toggle.
- **Key config:** `renderSideBySide: true` (toggleable), `readOnly: true`, `originalEditable: false`.

### 4c. Inline Spec Editing (Future — Optional)

- **Mode:** Regular editor, markdown language.
- **Purpose:** If Milkdown proves too heavy or complex for inline node editing, Monaco in markdown mode is a viable fallback.
- **Behavior:** Lightweight single-line or multi-line Monaco instance per active node, with custom keybinding overrides to prevent conflicts with tree navigation.
- **Note:** This is a fallback path. Milkdown is the primary choice for inline editing. Monaco is the fallback if WYSIWYG markdown editing proves problematic.

### Monaco Bundle Optimization

Monaco is large (~2.5 MB). Mitigation strategies:

| Strategy | Details |
|----------|---------|
| **Web Workers** | Use `monaco-editor/esm/vs/editor/editor.worker` with Vite's worker bundling. Configure via `vite-plugin-monaco-editor` or manual worker setup. |
| **Language subset** | Only register languages actually needed (markdown, typescript, javascript, python, rust, json, yaml, html, css). Avoid loading all 70+ grammars. |
| **Lazy loading** | The bottom drawer and agent detail panel are not visible on startup. Dynamically import Monaco only when the user first opens these views. |
| **Vite chunking** | Configure `manualChunks` in `vite.config.ts` to isolate Monaco into its own chunk so it doesn't block initial page load. |

```typescript
// vite.config.ts — Monaco chunking example
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          monaco: ['monaco-editor'],
        },
      },
    },
  },
});
```

---

## 5. Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tauri version | **v2** | Stable, better multi-platform, improved IPC, security. |
| Svelte version | **5** | Runes (`$state`, `$derived`, `$effect`) are simpler than stores for complex state. |
| Component library | **None (custom + Tailwind)** | Full control over tree UI, minimal dependencies, matches existing custom GPUI components. |
| Markdown editor | **Milkdown** | Per `single-pane-tree-plan.md`, WYSIWYG markdown editing with ProseMirror core. |
| Code viewer/editor | **Monaco Editor** | Industry-standard code editor (VS Code core). Syntax highlighting for all languages, diff viewer, minimap, line numbers, folding. Superior to CodeMirror for this use case due to built-in diff editor and richer feature set. |
| Terminal | **xterm.js** | Per `single-pane-tree-plan.md`, streaming terminal output. |
| State management | **Svelte 5 runes** | Single `AppState` class with `$state` fields, no external state library. |
| Backend comms | **Direct WebSocket** | Same JSON-RPC 2.0 protocol, no Tauri proxy overhead. |
| Testing | **Vitest + Testing Library** | Fast, Svelte-native, Vite-integrated. |

---

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| **Monaco bundle size (~2.5 MB)** | Lazy-load Monaco on first use of Code tab or Agent panel. Use `manualChunks` in Vite. Register only needed languages. Ship worker separately. |
| **Monaco in Svelte lifecycle** | Wrap in a dedicated `MonacoEditor.svelte` component with `onMount`/`onDestroy` for create/dispose. Use `ResizeObserver` or `automaticLayout: true` for responsive sizing. |
| **Milkdown complexity** | Start with a plain `<textarea>` for inline editing in Phase 5, swap in Milkdown once tree UX is stable. Monaco markdown mode as fallback. |
| **Virtual scrolling performance** | Profile early with 500+ nodes. Consider `svelte-virtual-list` or a custom intersection-observer approach. |
| **WebSocket in Tauri webview** | CSP must allow `ws://127.0.0.1:8000`. Tauri v2's CSP config handles this. |
| **Tauri + Svelte 5 compatibility** | `@tauri-apps/plugin-*` ecosystem is Svelte-agnostic (plain JS APIs). No framework conflicts expected. |
| **Loss of GPUI rendering performance** | The tree UI is not GPU-intensive. DOM rendering with virtual scrolling will be sufficient. |
| **Cross-platform parity** | Tauri v2 supports macOS/Windows/Linux. Test on all three early. |
| **Monaco + Milkdown keyboard conflicts** | When Monaco/Milkdown is focused, prevent tree-level keybindings (up/down/tab) from firing. Use a focus-aware keybinding layer at the app shell. |

---

## 7. Estimated Effort

| Phase | Effort | Dependency |
|-------|--------|------------|
| 1. Scaffold | 1 day | None |
| 2. State + Backend | 2–3 days | Phase 1 |
| 3. Theme (incl. Monaco theme) | 1–2 days | Phase 1 |
| 4. Components (incl. MonacoEditor) | 3–4 days | Phase 2, 3 |
| 5. Spec Tree | 3–4 days | Phase 4 |
| 6. Bottom Drawer (Monaco + xterm) | 2–3 days | Phase 5 |
| 7. Agent Integration (incl. diff viewer) | 2–3 days | Phase 5 |
| 8. Keybindings + Polish | 2 days | Phase 5–7 |
| 9. Testing | 2–3 days | Phase 5–7 |
| 10. Archive + Cleanup | 0.5 days | Phase 9 |
| **Total** | **~18–25 days** | |

Phases 3, 4, and 6–7 can partially overlap since they have different concerns.

---

## 8. Dev Workflow After Migration

```bash
# Start Python backend
uv run taui

# Start Tauri dev (in separate terminal)
cd app
npm run tauri dev    # Hot-reloading Svelte + Tauri native window

# Run tests
cd app
npm run test         # Vitest unit tests
npm run test:e2e     # E2E tests (Playwright)

# Build for distribution
cd app
npm run tauri build  # Produces .dmg (macOS), .msi (Windows), .deb/.AppImage (Linux)
```
