/**
 * Connection manager: initialises the WebSocket, loads the tangle snapshot,
 * and wires notification routing.
 *
 * Call `startConnection()` once on app mount.
 * Call `stopConnection()` on app destroy.
 */

import { appState } from '$stores/app-state.svelte'
import { backendClient } from '$services/backend-client'
import { handleNotification } from '$services/notifications'
import { applyPersistedFoldState } from '$services/fold-state'
import type { NotificationEvent } from '$services/backend-client'
import { agentStateFromString } from '$types/index'

function onConnectionState(ev: Event): void {
  const state = (ev as CustomEvent<string>).detail
  if (state === 'connecting') {
    appState.connectionState = 'connecting'
  } else if (state === 'open') {
    // Socket opened — kick off init sequence.
    _initialize().catch((err: unknown) => {
      console.error('[connection] init failed', err)
      appState.connectionState = { error: String(err) }
    })
  } else if (state === 'closed') {
    appState.connectionState = 'offline'
  }
}

function onNotification(ev: Event): void {
  const notification = (ev as NotificationEvent).detail
  handleNotification(notification)
}

async function _initialize(): Promise<void> {
  appState.connectionState = 'connecting'

  // 1. Handshake
  const initResult = await backendClient.initialize()
  if (initResult.model) {
    appState.currentModel = initResult.model
  }

  // Derive project title — prefer the value resolved by the backend (from
  // index.md front-matter / H1 / folder name), fall back to workspace folder.
  if (initResult.projectTitle) {
    appState.projectTitle = initResult.projectTitle
  } else if (initResult.workspace) {
    appState.projectTitle = initResult.workspace.split('/').filter(Boolean).pop() ?? null
  }

  // 2. Load full UI snapshot
  const snapshotRaw = await backendClient.uiSnapshot() as {
    tabs?: { open?: string[]; active?: string }
    layout?: { sidebarCollapsed?: boolean }
    theme?: 'dark' | 'light'
    tangleTree?: Parameters<typeof appState.hydrateFromBackend>[0]
  }
  appState.hydrateFromBackend(snapshotRaw.tangleTree ?? [])

  // Restore tabs/layout from backend snapshot
  const { tabStore } = await import('$stores/tabs.svelte')
  tabStore.applySnapshot(snapshotRaw.tabs ?? { open: [], active: '' })
  if (snapshotRaw.layout && typeof snapshotRaw.layout.sidebarCollapsed === 'boolean') {
    const { fileTree } = await import('$stores/file-tree.svelte')
    fileTree.sidebarCollapsed = snapshotRaw.layout.sidebarCollapsed
  }
  if (snapshotRaw.theme === 'dark' || snapshotRaw.theme === 'light') {
    const { theme } = await import('$stores/theme.svelte')
    theme.applySnapshot(snapshotRaw.theme)
  }
  applyPersistedFoldState()

  // 3. Restore Prime conversation history
  try {
    const { messages, has_more, oldest_seq } = await backendClient.primeHistory({
      limit: 50,
      full: true,
    })
    if (messages && messages.length > 0) {
      appState.restorePrimeHistory(messages, {
        hasMore: has_more,
        oldestSeq: oldest_seq,
      })
    } else {
      appState.restorePrimeHistory([], {
        hasMore: has_more,
        oldestSeq: oldest_seq,
      })
    }
  } catch (err) {
    console.warn('[connection] failed to restore prime history', err)
  }

  // 4. Re-subscribe to active agents
  try {
    const { agents } = await backendClient.agentList()
    for (const agent of agents) {
      // Update agent state in the store
      appState.upsertAgent({
        agentId: agent.agent_id,
        specRef: agent.tangle_ref ?? agent.spec_ref ?? '',
        state: agentStateFromString(agent.state),
        tier: (agent.tier as 'high' | 'medium' | 'low') ?? 'medium',
        agentType: (agent.agent_type as 'root' | 'minion') ?? 'root',
        displayName: agent.display_name,
      })
      // Re-subscribe for live events
      try {
        const backlog = await backendClient.agentSubscribe(agent.agent_id)
        if (backlog && backlog.length > 0) {
          appState.setDetailBacklog(agent.agent_id, backlog as Parameters<typeof appState.setDetailBacklog>[1])
        }
      } catch {
        // Agent may have finished between list and subscribe
      }
    }
  } catch (err) {
    console.warn('[connection] failed to restore agents', err)
  }
}

// ─── Public API ───────────────────────────────────────────────────────────────

export function startConnection(): void {
  backendClient.addEventListener('connectionState', onConnectionState)
  backendClient.addEventListener('notification', onNotification)
  backendClient.connect()
}

export function stopConnection(): void {
  backendClient.removeEventListener('connectionState', onConnectionState)
  backendClient.removeEventListener('notification', onNotification)
  backendClient.destroy()
}
