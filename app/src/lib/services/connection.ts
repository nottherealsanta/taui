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
import type { AgentDetailEvent } from '$types/index'
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
    theme?: 'dark' | 'light' | 'system' | null
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
    // Only apply if this is an explicit user preference — 'system'/null means
    // "follow OS", so the store's system-detection is already correct.
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
      // Re-subscribe for live events (offset-based catch-up when available)
      try {
        const lastOffset = appState.getDetailOffset(agent.agent_id)
        const fromOffset = lastOffset !== undefined ? lastOffset + 1 : undefined
        const { backlog, lastOffset: newLastOffset } = await backendClient.agentSubscribe(agent.agent_id, fromOffset)
        if (backlog && backlog.length > 0) {
          if (fromOffset !== undefined) {
            // Offset-based catch-up: append missed events instead of replacing
            const parsed = (backlog as Array<Record<string, unknown>>)
              .map((raw) => parseSubscribeEvent(raw))
              .filter((e): e is NonNullable<typeof e> => e !== null)
            for (const event of parsed) {
              appState.appendDetailEvent(agent.agent_id, event)
            }
          } else {
            appState.setDetailBacklog(agent.agent_id, backlog as Parameters<typeof appState.setDetailBacklog>[1], newLastOffset)
          }
          if (newLastOffset !== undefined) {
            appState.detailOffsets.set(agent.agent_id, newLastOffset)
          }
        }
      } catch {
        // Agent may have finished between list and subscribe
      }
    }
  } catch (err) {
    console.warn('[connection] failed to restore agents', err)
  }
}

// ─── Event parser for durable stream catch-up ────────────────────────────────

function parseSubscribeEvent(raw: Record<string, unknown>): AgentDetailEvent | null {
  const type = raw['type'] as string
  switch (type) {
    case 'message': return { type: 'message', role: (raw['role'] as string) ?? 'assistant', content: (raw['content'] as string) ?? '' }
    case 'tool_call': return { type: 'toolCall', callId: (raw['call_id'] as string) ?? '', toolName: (raw['tool_name'] as string) ?? '', arguments: raw['arguments'] ?? {} }
    case 'tool_result': return { type: 'toolResult', callId: (raw['call_id'] as string) ?? '', output: (raw['output'] as string) ?? null, error: (raw['error'] as string) ?? null, durationMs: (raw['duration_ms'] as number) ?? null }
    case 'token': return { type: 'token', text: (raw['text'] as string) ?? '' }
    case 'state_change': return { type: 'stateChange', state: agentStateFromString((raw['state'] as string) ?? 'idle') }
    default: return null
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
