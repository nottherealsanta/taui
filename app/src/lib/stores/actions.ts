/**
 * UI action dispatcher.
 * Ported from ui/src/app/actions.rs.
 *
 * Pure state mutations that do NOT call the backend directly.
 * Backend RPCs are initiated by the connection manager based on returned signals.
 */

import type { NodeId, SpecRef } from '$types/index'
import { appState } from './app-state.svelte'

// ─── Action types ──────────────────────────────────────────────────────────────

export type UiAction =
  | { type: 'selectNode'; nodeId: NodeId }
  | { type: 'selectNext' }
  | { type: 'selectPrevious' }
  | { type: 'addSiblingNode' }
  | { type: 'indentNode' }
  | { type: 'outdentNode' }
  | { type: 'toggleCollapse' }
  | { type: 'enterEditing' }
  | { type: 'exitEditing' }

// ─── Dispatch ────────────────────────────────────────────────────────────────

/**
 * Dispatch a UI action against the global app state.
 * Returns true if the state actually changed (useful for dirty-checking).
 */
export function dispatch(action: UiAction): boolean {
  switch (action.type) {
    case 'selectNode':
      if (appState.selectedNode === action.nodeId) return false
      appState.setSelected(action.nodeId)
      appState.editorMode = 'selection'
      return true

    case 'selectNext':
      return moveSelection(1)

    case 'selectPrevious':
      return moveSelection(-1)

    case 'addSiblingNode':
      return addSiblingNode()

    case 'indentNode':
      return indentSelected()

    case 'outdentNode':
      return outdentSelected()

    case 'toggleCollapse':
      return appState.toggleCollapse()

    case 'enterEditing':
      if (appState.selectedNode === null) return false
      appState.editorMode = 'editing'
      return true

    case 'exitEditing':
      if (appState.editorMode !== 'editing') return false
      appState.editorMode = 'selection'
      return true
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function moveSelection(delta: number): boolean {
  // Skip code_ref sub-rows — arrow keys navigate only real spec nodes.
  const flattened = appState.flattenedNodes.filter((n) => n.kind !== 'codeRef')
  if (flattened.length === 0) return false

  const current = appState.selectedNode !== null
    ? flattened.findIndex((row) => row.id === appState.selectedNode)
    : 0

  const idx = current === -1 ? 0 : current
  const target = Math.max(0, Math.min(flattened.length - 1, idx + delta))

  if (idx === target && current !== -1) return false

  appState.setSelected(flattened[target].id)
  appState.editorMode = 'selection'
  return true
}

function addSiblingNode(): boolean {
  const selected = appState.selectedNode
  const parent = selected !== null ? (appState.nodes[selected]?.parent ?? null) : null

  // Generate a local temporary ref; will be replaced on next backend sync.
  const tmpRef: SpecRef = `local/new-${appState.nodes.length}`
  const newId = appState.createNode(tmpRef, '', parent)

  const siblings = appState.siblings(parent)
  const insertionIndex = selected !== null
    ? (siblings.indexOf(selected) + 1 || siblings.length)
    : siblings.length

  // Splice the new node into the sibling list.
  siblings.splice(insertionIndex, 0, newId)

  appState.setSelected(newId)
  appState.editorMode = 'editing'
  return true
}

function indentSelected(): boolean {
  const selected = appState.selectedNode
  if (selected === null) return false

  const parent = appState.nodes[selected]?.parent ?? null
  const sibs = appState.siblings(parent)
  const index = sibs.indexOf(selected)

  if (index <= 0) return false // no previous sibling to become the parent

  const newParent = sibs[index - 1]

  sibs.splice(index, 1)
  appState.nodes[selected].parent = newParent
  appState.nodes[newParent].children.push(selected)
  return true
}

function outdentSelected(): boolean {
  const selected = appState.selectedNode
  if (selected === null) return false

  const parent = appState.nodes[selected]?.parent ?? null
  if (parent === null) return false // already a root node

  const grandParent = appState.nodes[parent]?.parent ?? null
  const indexInParent = appState.nodes[parent].children.indexOf(selected)
  if (indexInParent === -1) return false

  appState.nodes[parent].children.splice(indexInParent, 1)

  const parentIndex = appState.siblings(grandParent).indexOf(parent)
  const insertAfter = parentIndex === -1
    ? appState.siblings(grandParent).length
    : parentIndex + 1

  appState.siblings(grandParent).splice(insertAfter, 0, selected)
  appState.nodes[selected].parent = grandParent
  return true
}
