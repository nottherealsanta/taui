---
title: Stateless UI
last_updated: 2026-04-10
---

# Stateless UI

Backend-driven UI state with snapshot/reconnect protocol. The frontend holds no authoritative state.

Depends on: [Server](../domains/server.md), [Frontend](../domains/frontend.md)

## Purpose

Make the UI resilient to page refresh, reconnection, and future multi-window scenarios. All persistent state lives in the backend — the UI is a pure renderer.

## User / Business Outcome

- Page refresh produces identical state — no data loss.
- Agent mid-reply survives refresh — conversation catches up from DB.
- Multiple windows (future) can independently connect to the same backend state.
- Backend crash recovery — on restart, reads DB and resumes from last persisted state.

## Scope

In scope:
- Snapshot RPC on connect (`ui.snapshot`)
- All UI state stored in backend: tabs, active tab, sidebar collapsed, split sizes, theme
- Svelte stores as thin mirrors over backend state (not independent state containers)
- Agent session re-subscription on reconnect
- `settings.json` as the persistence layer for UI settings

Out of scope:
- Toast notifications (ephemeral, stays in UI)
- Hover states, animations, focus tracking (ephemeral)
- Modal open/close (ephemeral)
- In-flight keystroke debouncing (ephemeral)

## Constraints

- UI never writes authoritative state to localStorage or any client-side store.
- Every user action that changes persistent state goes through an RPC call to the backend.
- Backend updates `settings.json`, then pushes the new state back to the UI.
- Svelte stores provide `applySnapshot()` methods to receive backend state.

## Design

### Reconnection Protocol

```
1. UI opens WebSocket -> sends "ui.snapshot" RPC
2. Backend reads settings.json + queries DB, returns full snapshot:
   {
     tabs: [...],
     activeTabId: "...",
     layout: { sidebarCollapsed, splitSizes },
     theme: "dark",
     tangleTree: [...],
     agentSessions: [{ id, status, lastMessageId }, ...]
   }
3. UI renders from snapshot — identical to state before disconnect
4. For each agentSession with status "streaming":
   - UI sends "agent.subscribe" RPC with session ID
   - Backend replays messages since lastMessageId
   - Backend continues pushing new events
5. User actions are intents:
   - User opens tab -> UI sends "ui.openTab" -> backend updates settings.json -> pushes update
   - User toggles sidebar -> UI sends "ui.updateLayout" -> backend updates -> pushes update
```

### Store Pattern

```typescript
// OLD: store owns state
class TabStore {
  tabs = $state<Tab[]>([])
  openTab(path: string) {
    this.tabs.push(newTab)
    localStorage.setItem('tabs', JSON.stringify(this.tabs))
  }
}

// NEW: store mirrors backend state
class TabStore {
  tabs = $state<Tab[]>([])
  async openTab(path: string) {
    await rpc('ui.openTab', { path })
  }
  applySnapshot(snapshot: TabSnapshot) {
    this.tabs = snapshot.tabs
  }
}
```

## Code References

- `taui/server/handlers.py` — `ui/snapshot`, `ui/openTab`, `ui/closeTab`, `ui/setActiveTab`, `ui/updateLayout`, `ui/setTheme`
- `app/src/stores/app-state.svelte.ts` — main app state store with `applySnapshot()`
- `app/src/stores/tabs.svelte.ts` — tab store (should be RPC-driven)
- `app/src/stores/theme.svelte.ts` — theme store (should be RPC-driven)
- `app/src/services/connection.ts` — reconnection and snapshot loading

## Tests / Verification

- `tests/test_settings.py` — settings.json read/write, snapshot construction, tab state, layout, theme
- `tests/test_server_app.py` — `ui.snapshot` RPC integration test

```
pytest tests/test_settings.py tests/test_server_app.py -q
```

## Open Questions

- How should the snapshot handle large tangle trees? Pagination or full dump?
- Should split pane sizes be stored with pixel precision or as percentages?

## Related Decisions

No decisions recorded yet.
