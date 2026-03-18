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
  await backendClient.initialize()

  // 2. Load the spec tree
  const tree = await backendClient.getTreeDetailed()
  appState.hydrateFromBackend(tree.nodes)
  applyPersistedFoldState()
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
