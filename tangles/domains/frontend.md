---
title: Frontend
last_updated: 2026-04-10
---

# Frontend

The Svelte 5 + Tauri desktop application — three-column layout, stateless stores, WebSocket communication.

## Responsibility

Renders the UI and sends user intents to the backend. The frontend holds no authoritative state — it is a pure renderer that receives state from backend snapshots and push updates. The single entry point is `app/src/App.svelte:App`, which composes the three-column shell and mounts all child panes.

Specifically:

- Three-column Obsidian-like layout: left nav (tangle tree), center editor (tangle content), right pane (agent chat) — wired in `app/src/App.svelte:App`
- Tangle file browsing, selection, and editing — driven by `app/src/lib/stores/file-tree.svelte.ts:FileTreeStore`
- Agent conversation display and interaction — session state lives in `app/src/lib/stores/app-state.svelte.ts:AppState` under the `agentSessions` field
- Tab management (open, close, switch) — handled by `app/src/lib/stores/tabs.svelte.ts:TabStore` via `openFile`, `closeTab`, `setActiveTab`
- Settings modal with prompt editing — RPC calls routed through `app/src/lib/services/backend-client.ts:BackendClient.promptsList`, `promptsUpdate`, and `promptsReset`
- Theme toggling (dark/light) — managed by `app/src/lib/stores/theme.svelte.ts:ThemeStore`; persisted via `app/src/lib/services/backend-client.ts:BackendClient.uiSetTheme`
- WebSocket connection management and reconnection — orchestrated by `app/src/lib/services/connection.ts:startConnection` / `stopConnection`

## Invariants

- The UI never computes authoritative state. It receives a full `Snapshot` (typed in `app/src/lib/types/index.ts:Snapshot`) from the backend and renders it via `app/src/lib/stores/app-state.svelte.ts:AppState.applySnapshot`.
- User interactions are **intents** sent to the backend via RPC through `app/src/lib/services/backend-client.ts:BackendClient.send`. The backend processes them and pushes updates.
- Page refresh = reconnect + snapshot. `app/src/lib/services/connection.ts:startConnection` re-establishes the WebSocket and calls `_loadSnapshot` to rehydrate all stores. No data loss.
- Agent mid-reply survives refresh: agent writes to DB as it streams; on reconnect, `app/src/lib/services/backend-client.ts:BackendClient.agentSubscribe` re-subscribes and catches up from DB.
- `app/src/lib/stores/toasts.svelte.ts:ToastStore` and hover states are the only ephemeral UI-side state — they are never sent to the backend.

## Interfaces

- WebSocket client connecting to backend `/ws` — established in `app/src/lib/services/backend-client.ts:BackendClient.connect`
- RPC namespaces:
  - `tangle.*` — `app/src/lib/services/backend-client.ts:BackendClient.tangleGetTree`, `tangleGetNode`, `tangleUpdateNode`
  - `ui.*` — `uiSnapshot`, `uiOpenTab`, `uiCloseTab`, `uiSetActiveTab`, `uiUpdateLayout`, `uiSetTheme`
  - `agent.*` — `agentSubscribe`, `agentSend`
  - `prompts.*` — `promptsList`, `promptsUpdate`, `promptsReset`
- All RPC request/response shapes are defined in `app/src/lib/types/index.ts`
- Tauri IPC for native window management (outside the WebSocket layer)

## Key Components

- **App Shell** (`app/src/App.svelte:App`) — Root layout with three-column split; reads `splitSizes` and `sidebarCollapsed` from `app/src/lib/stores/app-state.svelte.ts:AppState`
- **Tangle Nav Sidebar** — Left pane: tangle file tree browser; backed by `app/src/lib/stores/file-tree.svelte.ts:FileTreeStore` which is populated from `app/src/lib/services/backend-client.ts:BackendClient.tangleGetTree`
- **Tangle Editor Pane** — Center pane: markdown editor with inline code ref rendering; reads the active node via `app/src/lib/stores/app-state.svelte.ts:AppState.setActiveNode` and writes via `BackendClient.tangleUpdateNode`
- **Agent Chat Pane** — Right pane: multi-tab agent conversation interface; tab state from `app/src/lib/stores/tabs.svelte.ts:TabStore`; messages from `app/src/lib/stores/app-state.svelte.ts:AppState` (`agentSessions` field); sends via `app/src/lib/services/backend-client.ts:BackendClient.agentSend`
- **Settings Modal** — Prompts editing, theme, layout preferences; uses `BackendClient.promptsList` / `promptsUpdate` / `promptsReset` and `BackendClient.uiSetTheme`
- **Backend Client** (`app/src/lib/services/backend-client.ts:BackendClient`) — WebSocket JSON-RPC client; `connect` (lines 80-130) opens the socket and registers push-update handlers; `send` (lines 132-165) serialises and dispatches every RPC call
- **Connection Service** (`app/src/lib/services/connection.ts:startConnection`) — Calls `BackendClient.connect`, then `_loadSnapshot` to drive `AppState.applySnapshot`; `stopConnection` tears the socket down cleanly
- **App State Store** (`app/src/lib/stores/app-state.svelte.ts:AppState`) — Central Svelte 5 runes store; holds `tangleTree`, `activeTab`, `tabs`, `sidebarCollapsed`, `splitSizes`, `theme`, `agentSessions`; `applySnapshot` is the single entry point for backend-driven state updates
- **Tab Store** (`app/src/lib/stores/tabs.svelte.ts:TabStore`) — Manages the ordered list of open tabs; `openFile` (line 35) adds a tab and calls `BackendClient.uiOpenTab`; `applySnapshot` (line 198) reconciles tab state from a backend snapshot
- **Actions** (`app/src/lib/stores/actions.ts`) — Thin action dispatchers that bridge raw UI events to the correct `BackendClient` RPC method, keeping component code free of transport details

## Code References

- `app/src/App.svelte:App`
- `app/src/lib/services/backend-client.ts:BackendClient` (lines 54-477)
  - `BackendClient.connect` (lines 80-130)
  - `BackendClient.send` (lines 132-165)
  - `BackendClient.uiSnapshot` (line 418), `uiOpenTab` (422), `uiCloseTab` (426), `uiSetActiveTab` (430), `uiUpdateLayout` (434), `uiSetTheme` (438)
  - `BackendClient.promptsList` (446), `promptsUpdate` (460), `promptsReset` (468)
  - `BackendClient.agentSubscribe` (390), `agentSend` (398)
  - `BackendClient.tangleGetTree` (350), `tangleGetNode` (354), `tangleUpdateNode` (358)
- `app/src/lib/services/connection.ts:startConnection` (line 158), `stopConnection` (line 164), `_loadSnapshot`
- `app/src/lib/stores/app-state.svelte.ts:AppState`
  - Fields: `tangleTree`, `activeTab`, `tabs`, `sidebarCollapsed`, `splitSizes`, `theme`, `agentSessions`
  - Methods: `applySnapshot`, `setTangleTree`, `setActiveNode`
- `app/src/lib/stores/tabs.svelte.ts:TabStore`
  - `TabStore.openFile` (line 35), `closeTab`, `setActiveTab`, `applySnapshot` (line 198)
- `app/src/lib/stores/theme.svelte.ts:ThemeStore`
- `app/src/lib/stores/toasts.svelte.ts:ToastStore`
- `app/src/lib/stores/file-tree.svelte.ts:FileTreeStore`
- `app/src/lib/stores/actions.ts`
- `app/src/lib/types/index.ts` — `Tab`, `TangleNode`, `TangleTree`, `AgentSession`, `AgentMessage`, `Snapshot`, `LayoutState`, `PromptEntry`
- `app/package.json`
- `app/vite.config.ts`
- `app/svelte.config.js`

## Verification

- `app/e2e/` — Playwright end-to-end tests
- Manual verification: launch app, verify three-column layout, tab operations, agent chat

```
npm run test --prefix app
```

## Related Features

- [Stateless UI](../features/stateless-ui.md)
- [Editable Prompts](../features/editable-prompts.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
