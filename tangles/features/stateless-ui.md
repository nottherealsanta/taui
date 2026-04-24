---
title: Stateless UI
last_updated: 2026-04-11
---

# Stateless UI

Backend-driven UI state with snapshot/reconnect protocol. The frontend holds no authoritative state.

Depends on: [Server](../domains/server.md), [Frontend](../domains/frontend.md)

## Purpose

- Make the UI resilient to page refresh, reconnection, and future multi-window scenarios.
- All persistent state lives in the backend — the UI is a pure renderer.

## User / Business Outcome

- Page refresh produces identical state — no data loss.
  - Agent mid-reply survives refresh — conversation catches up from DB.
- Multiple windows (future) can independently connect to the same backend state.
- Backend crash recovery — on restart, reads DB and resumes from last persisted state.

## Scope

- **In scope**
  - Snapshot RPC on connect (`ui.snapshot`)
  - All UI state stored in backend: tabs, active tab, sidebar collapsed, split sizes, theme
  - Svelte stores as thin mirrors over backend state (not independent state containers)
  - Agent session re-subscription on reconnect
  - `settings.json` as the persistence layer for UI settings
- **Out of scope** (ephemeral, stays in UI)
  - Toast notifications
  - Hover states, animations, focus tracking
  - Modal open/close
  - In-flight keystroke debouncing

## Constraints

- UI never writes authoritative state to localStorage or any client-side store.
- Every user action that changes persistent state goes through an RPC call to the backend.
  - Backend updates `settings.json`, then pushes the new state back to the UI.
  - `taui/server/handlers.py:_handle_ui_snapshot` — snapshot construction
  - `taui/config/project_settings.py:ProjectSettingsStore.save` — writes settings.json
- Svelte stores provide `applySnapshot()` methods to receive backend state.
  - `app/src/lib/stores/tabs.svelte.ts:TabStore.applySnapshot` — applies backend snapshot

## Design

- **Reconnection protocol**
  1. UI opens WebSocket → sends `ui.snapshot` RPC
     - `app/src/lib/services/backend-client.ts:BackendClient.uiSnapshot` — snapshot RPC call
     - `app/src/lib/services/connection.ts:startConnection` — init + snapshot loading
  2. Backend reads `settings.json` + queries DB, returns full snapshot:
     - Fields: `tabs`, `activeTabId`, `layout` (`sidebarCollapsed`, `splitSizes`), `theme`, `tangleTree`, `agentSessions`
     - `taui/config/project_settings.py:ProjectSettingsStore.load` — reads settings.json with defaults merge
  3. UI renders from snapshot — identical to state before disconnect
  4. For each `agentSession` with `status: "streaming"`:
     - UI sends `agent.subscribe` RPC with session ID
     - Backend replays messages since `lastMessageId`, then continues pushing new events
  5. User actions are intents — UI sends RPC → backend updates → backend pushes update
     - Open tab: `ui.openTab` → `taui/server/handlers.py:_handle_ui_open_tab`
     - Close tab: `ui.closeTab` → `taui/server/handlers.py:_handle_ui_close_tab`
     - Set active tab: `ui.setActiveTab` → `taui/server/handlers.py:_handle_ui_set_active_tab`
     - Toggle sidebar: `ui.updateLayout` → `taui/server/handlers.py:_handle_ui_update_layout`
     - Set theme: `ui.setTheme` → `taui/server/handlers.py:_handle_ui_set_theme`
- **Store pattern** — stores mirror backend state rather than owning it
  - `app/src/lib/stores/app-state.svelte.ts:AppState` — main reactive store
  - `app/src/lib/stores/tabs.svelte.ts:TabStore` — tab state mirror
  - Each store exposes `applySnapshot()` instead of writing directly to local storage
- **Settings persistence**
  - `taui/config/project_settings.py:ProjectSettingsStore` — settings persistence class

## Tests / Verification

- `tests/test_settings.py` — settings.json read/write, snapshot construction, tab state, layout, theme
- `tests/test_server_app.py` — `ui.snapshot` RPC integration test
- Run: `pytest tests/test_settings.py tests/test_server_app.py -q`

## Open Questions

- How should the snapshot handle large tangle trees? Pagination or full dump?
- Should split pane sizes be stored with pixel precision or as percentages?

## Related Decisions

No decisions recorded yet.
