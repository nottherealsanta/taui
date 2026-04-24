---
title: Frontend
last_updated: 2026-04-11
---

# Frontend

The Svelte 5 + Tauri desktop application — three-column layout, stateless stores, WebSocket communication.

## Responsibility

Renders the UI and sends user intents to the backend. The frontend holds no authoritative state — it is a pure renderer that receives state from backend snapshots and push updates.

- **Layout** — three-column Obsidian-like shell wired in `app/src/App.svelte:App`
  - Left nav: tangle file tree browser
  - Center: markdown editor with inline code ref rendering
  - Right: multi-tab agent chat pane
- **Tangle browsing & editing** — driven by `app/src/lib/stores/file-tree.svelte.ts:FileTreeStore`
  - Selection and editing via `app/src/lib/stores/app-state.svelte.ts:AppState.setActiveNode`
  - Writes routed through `app/src/lib/services/backend-client.ts:BackendClient.tangleUpdateNode`
- **Agent conversations** — session state in `app/src/lib/stores/app-state.svelte.ts:AppState` (`agentSessions` field)
  - Tab management via `app/src/lib/stores/tabs.svelte.ts:TabStore` (`openFile`, `closeTab`, `setActiveTab`)
- **Settings modal** — prompt editing and preferences
  - RPC calls: `app/src/lib/services/backend-client.ts:BackendClient.promptsList`, `promptsUpdate`, `promptsReset`
- **Theme toggling** — managed by `app/src/lib/stores/theme.svelte.ts:ThemeStore`
  - Persisted via `app/src/lib/services/backend-client.ts:BackendClient.uiSetTheme`
- **WebSocket lifecycle** — orchestrated by `app/src/lib/services/connection.ts:startConnection` / `stopConnection`

## Invariants

- The UI never computes authoritative state
  - Receives a full `Snapshot` (typed in `app/src/lib/types/index.ts:Snapshot`) from the backend
  - Applied via `app/src/lib/stores/app-state.svelte.ts:AppState.applySnapshot`
- User interactions are **intents** sent via RPC through `app/src/lib/services/backend-client.ts:BackendClient.send`
  - The backend processes them and pushes updates; the UI never mutates state directly
- Page refresh = reconnect + snapshot — no data loss
  - `app/src/lib/services/connection.ts:startConnection` re-establishes the WebSocket and calls `_loadSnapshot` to rehydrate all stores
- Agent mid-reply survives refresh
  - Agent writes to DB as it streams; on reconnect `app/src/lib/services/backend-client.ts:BackendClient.agentSubscribe` re-subscribes and catches up from DB
- `app/src/lib/stores/toasts.svelte.ts:ToastStore` and hover states are the only ephemeral UI-side state — never sent to the backend

## Interfaces

- **WebSocket client** — connects to backend `/ws` via `app/src/lib/services/backend-client.ts:BackendClient.connect`
- **RPC namespaces** — all shapes defined in `app/src/lib/types/index.ts`
  - `tangle.*` — `tangleGetTree`, `tangleGetNode`, `tangleUpdateNode`
  - `ui.*` — `uiSnapshot`, `uiOpenTab`, `uiCloseTab`, `uiSetActiveTab`, `uiUpdateLayout`, `uiSetTheme`
  - `agent.*` — `agentSubscribe`, `agentSend`
  - `prompts.*` — `promptsList`, `promptsUpdate`, `promptsReset`
- **Tauri IPC** — native window management (outside the WebSocket layer)

## Key Components

- **App Shell** (`app/src/App.svelte:App`) — root layout with three-column split
  - Reads `splitSizes` and `sidebarCollapsed` from `app/src/lib/stores/app-state.svelte.ts:AppState`
- **Backend Client** (`app/src/lib/services/backend-client.ts:BackendClient`, lines 54–477) — WebSocket JSON-RPC client
  - `connect` (lines 80–130) opens the socket and registers push-update handlers
  - `send` (lines 132–165) serialises and dispatches every RPC call
  - UI methods: `uiSnapshot` (418), `uiOpenTab` (422), `uiCloseTab` (426), `uiSetActiveTab` (430), `uiUpdateLayout` (434), `uiSetTheme` (438)
  - Prompts methods: `promptsList` (446), `promptsUpdate` (460), `promptsReset` (468)
  - Agent methods: `agentSubscribe` (390), `agentSend` (398)
  - Tangle methods: `tangleGetTree` (350), `tangleGetNode` (354), `tangleUpdateNode` (358)
- **Connection Service** (`app/src/lib/services/connection.ts:startConnection`, line 158) — orchestrates connect and snapshot load
  - Calls `BackendClient.connect`, then `_loadSnapshot` → `AppState.applySnapshot`
  - `stopConnection` (line 164) tears the socket down cleanly
- **App State Store** (`app/src/lib/stores/app-state.svelte.ts:AppState`) — central Svelte 5 runes store
  - Fields: `tangleTree`, `activeTab`, `tabs`, `sidebarCollapsed`, `splitSizes`, `theme`, `agentSessions`
  - Methods: `applySnapshot` (single entry point for backend-driven updates), `setTangleTree`, `setActiveNode`
- **Tab Store** (`app/src/lib/stores/tabs.svelte.ts:TabStore`) — manages the ordered list of open tabs
  - `openFile` (line 35) adds a tab and calls `BackendClient.uiOpenTab`
  - `applySnapshot` (line 198) reconciles tab state from a backend snapshot
- **File Tree Store** (`app/src/lib/stores/file-tree.svelte.ts:FileTreeStore`) — populated from `BackendClient.tangleGetTree`
- **Actions** (`app/src/lib/stores/actions.ts`) — thin dispatchers bridging raw UI events to `BackendClient` RPC methods
- **DisclosureList Extension** (`app/src/lib/extensions/disclosure-list.ts:DisclosureList`, lines 144–229) — TipTap ProseMirror plugin for progressive disclosure in the tangle editor
  - List items with children get a clickable chevron; collapsed state tracked per-position and remapped on doc changes
  - Key internals: `listItemHasNestedList` (line 31), `findNestedListPos` (line 44), `buildDecorations` (line 61), `remapCollapsed` (line 132)
  - CSS classes drive visibility toggling and hierarchy indicators

## Verification

- `app/e2e/` — Playwright end-to-end tests
- Manual: launch app, verify three-column layout, tab operations, agent chat

```
npm run test --prefix app
```

## Related Features

- [Stateless UI](../features/stateless-ui.md)
- [Editable Prompts](../features/editable-prompts.md)
- [Progressive Disclosure](../features/progressive-disclosure.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
