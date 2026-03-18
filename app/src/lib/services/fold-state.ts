/**
 * Fold state persistence.
 * Saves/restores collapsed state for each spec node keyed by spec_ref.
 * Wire up by calling startFoldPersistence() once after tree is hydrated.
 */

import { appState } from '$stores/app-state.svelte'

const PREFIX = 'taui-fold:'

export function saveFoldState(specRef: string, collapsed: boolean): void {
  try {
    if (collapsed) {
      localStorage.setItem(PREFIX + specRef, '1')
    } else {
      localStorage.removeItem(PREFIX + specRef)
    }
  } catch { /* sandboxed */ }
}

export function loadFoldState(specRef: string): boolean {
  try {
    return localStorage.getItem(PREFIX + specRef) === '1'
  } catch {
    return false
  }
}

/**
 * Apply persisted fold state to all nodes after hydration.
 * Call once immediately after appState.hydrateFromBackend().
 */
export function applyPersistedFoldState(): void {
  for (const node of appState.nodes) {
    // Never collapse the primary root
    if (appState.primaryRootId === node.id) continue
    node.collapsed = loadFoldState(node.specRef)
  }
}

/**
 * Returns a cleanup function.
 * Sets up a reactive $effect (must be called inside a Svelte component or $effect root)
 * that syncs collapse changes back to localStorage.
 *
 * Use like:
 *   let cleanup = watchFoldState()
 *   onDestroy(cleanup)
 */
export function watchFoldState(): () => void {
  // We track the previous snapshot of collapsed states to detect changes.
  let prev = new Map<string, boolean>()

  // Polling via requestAnimationFrame is used instead of $effect to avoid
  // being tied to a specific component's lifecycle.
  let rafId = 0
  let active = true

  function tick() {
    if (!active) return
    for (const node of appState.nodes) {
      const was = prev.get(node.specRef)
      if (was !== node.collapsed) {
        saveFoldState(node.specRef, node.collapsed)
        prev.set(node.specRef, node.collapsed)
      }
    }
    rafId = requestAnimationFrame(tick)
  }

  rafId = requestAnimationFrame(tick)

  return () => {
    active = false
    cancelAnimationFrame(rafId)
  }
}
