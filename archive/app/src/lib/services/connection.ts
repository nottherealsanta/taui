/**
 * Connection manager: initialises the WebSocket, loads the spec tree,
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

  // 2. Load the spec tree
  const tree = await backendClient.getTreeDetailed()
  appState.hydrateFromBackend(tree.nodes)
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
        specRef: agent.spec_ref,
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
