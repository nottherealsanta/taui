---
title: Frontend
last_updated: 2026-04-10
---

# Frontend

The Svelte 5 + Tauri desktop application — three-column layout, stateless stores, WebSocket communication.

## Responsibility

Renders the UI and sends user intents to the backend. The frontend holds no authoritative state — it is a pure renderer that receives state from backend snapshots and push updates.

Specifically:

- Three-column Obsidian-like layout: left nav (tangle tree), center editor (tangle content), right pane (agent chat)
- Tangle file browsing, selection, and editing
- Agent conversation display and interaction
- Tab management (open, close, switch)
- Settings modal with prompt editing
- Theme toggling (dark/light)
- WebSocket connection management and reconnection

## Invariants

- The UI never computes authoritative state. It receives state from the backend and renders it.
- User interactions are **intents** sent to the backend via RPC. The backend processes them and pushes updates.
- Page refresh = reconnect + snapshot. No data loss.
- Agent mid-reply survives refresh: agent writes to DB as it streams; on reconnect, catch up from DB and re-subscribe.
- Toast notifications and hover states are the only ephemeral UI-side state.

## Interfaces

- WebSocket client connecting to backend `/ws`
- RPC calls: `tangle.*`, `ui.*`, `agent.*`, `prompts.*`
- Tauri IPC for native window management

## Key Components

- **App Shell** (`app/src/App.svelte`) — Root layout with three-column split
- **Tangle Nav Sidebar** — Left pane: tangle file tree browser
- **Tangle Editor Pane** — Center pane: markdown editor with inline code ref rendering
- **Agent Chat Pane** — Right pane: multi-tab agent conversation interface
- **Settings Modal** — Prompts editing, theme, layout preferences
- **Backend Client** (`app/src/services/backend-client.ts`) — WebSocket JSON-RPC client
- **Connection Service** (`app/src/services/connection.ts`) — Reconnection, snapshot loading
- **Stores** (`app/src/stores/`) — Svelte 5 runes-based state that mirrors backend

## Code References

- `app/src/App.svelte`
- `app/src/services/backend-client.ts`
- `app/src/services/connection.ts`
- `app/src/stores/app-state.svelte.ts`
- `app/src/stores/tabs.svelte.ts`
- `app/src/stores/theme.svelte.ts`
- `app/src/stores/toasts.svelte.ts`
- `app/src/stores/file-tree.svelte.ts`
- `app/src/stores/actions.ts`
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
