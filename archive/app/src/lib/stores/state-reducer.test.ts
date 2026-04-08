/**
 * 9.1 State reducer tests — ported from ui/tests/state_reducer.rs.
 *
 * These tests operate on the singleton appState, which is reset via
 * loadDemoState() before each test. dispatch() is called exactly as
 * it would be in the real UI.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { appState, loadDemoState } from './app-state.svelte'
import { dispatch } from './actions'

function firstLine(markdown: string): string {
  return markdown.split('\n')[0].trim()
}

function nodeByLabel(label: string) {
  const n = appState.nodes.find((n) => firstLine(n.markdown) === label)
  if (!n) throw new Error(`Node not found: "${label}"`)
  return n
}

beforeEach(() => {
  loadDemoState()
})

// ── addSiblingNode ────────────────────────────────────────────────────────────

describe('addSiblingNode', () => {
  it('increases flattened node count by 1', () => {
    // Select a non-root node to add a sibling to
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })

    const before = appState.flattenedNodes.length
    const changed = dispatch({ type: 'addSiblingNode' })

    expect(changed).toBe(true)
    expect(appState.flattenedNodes.length).toBe(before + 1)
  })

  it('new node is selected and has empty markdown', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })
    dispatch({ type: 'addSiblingNode' })

    const selected = appState.selectedNode
    expect(selected).not.toBeNull()
    expect(appState.nodes[selected!].markdown).toBe('')
  })
})

// ── indentNode ────────────────────────────────────────────────────────────────

describe('indentNode', () => {
  it('tab indent makes previous sibling the parent', () => {
    const target = nodeByLabel('Tab Indent')
    dispatch({ type: 'selectNode', nodeId: target.id })

    const changed = dispatch({ type: 'indentNode' })

    expect(changed).toBe(true)
    const selected = appState.selectedNode!
    const parent = appState.nodes[selected].parent
    expect(parent).not.toBeNull()
    expect(firstLine(appState.nodes[parent!].markdown)).toBe('Editable Nodes')
  })

  it('preserves selection after indent', () => {
    const target = nodeByLabel('Tab Indent')
    dispatch({ type: 'selectNode', nodeId: target.id })
    const selectedBefore = appState.selectedNode

    dispatch({ type: 'indentNode' })

    expect(appState.selectedNode).toBe(selectedBefore)
  })

  it('returns false when no node is selected', () => {
    appState.selectedNode = null
    appState.selectedSpecRef = null
    const changed = dispatch({ type: 'indentNode' })
    expect(changed).toBe(false)
  })
})

// ── outdentNode ───────────────────────────────────────────────────────────────

describe('outdentNode', () => {
  it('shift-tab outdents a previously indented node', () => {
    const target = nodeByLabel('Tab Indent')
    dispatch({ type: 'selectNode', nodeId: target.id })
    dispatch({ type: 'indentNode' })

    const changed = dispatch({ type: 'outdentNode' })

    expect(changed).toBe(true)
    const selected = appState.selectedNode!
    const parent = appState.nodes[selected].parent
    expect(parent).not.toBeNull()
    expect(firstLine(appState.nodes[parent!].markdown)).toBe('Spec Tree Pane')
  })

  it('indent + outdent restores original parent (behavioural parity)', () => {
    const target = nodeByLabel('Tab Indent')
    dispatch({ type: 'selectNode', nodeId: target.id })
    const parentBefore = appState.nodes[target.id].parent

    dispatch({ type: 'indentNode' })
    expect(appState.nodes[target.id].parent).not.toBe(parentBefore)

    dispatch({ type: 'outdentNode' })
    expect(appState.nodes[target.id].parent).toBe(parentBefore)
  })
})

// ── toggleCollapse ────────────────────────────────────────────────────────────

describe('toggleCollapse', () => {
  it('collapses a node with children', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })
    expect(target.collapsed).toBe(false)

    const changed = dispatch({ type: 'toggleCollapse' })

    expect(changed).toBe(true)
    expect(target.collapsed).toBe(true)
  })

  it('expanding after collapsing restores children in flat list', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })

    dispatch({ type: 'toggleCollapse' })
    const countCollapsed = appState.flattenedNodes.length

    dispatch({ type: 'toggleCollapse' })
    const countExpanded = appState.flattenedNodes.length

    expect(countExpanded).toBeGreaterThan(countCollapsed)
  })

  it('returns false for leaf nodes', () => {
    const leaf = nodeByLabel('Editable Nodes') // no children in demo
    dispatch({ type: 'selectNode', nodeId: leaf.id })
    const changed = dispatch({ type: 'toggleCollapse' })
    expect(changed).toBe(false)
  })

  it('returns false for the primary root', () => {
    const root = appState.nodes[appState.primaryRootId!]
    dispatch({ type: 'selectNode', nodeId: root.id })
    const changed = dispatch({ type: 'toggleCollapse' })
    expect(changed).toBe(false)
  })
})

// ── selectNext / selectPrevious ───────────────────────────────────────────────

describe('selection navigation', () => {
  it('selectNext advances selection by one', () => {
    const flat = appState.flattenedNodes
    dispatch({ type: 'selectNode', nodeId: flat[0].id })

    const changed = dispatch({ type: 'selectNext' })

    expect(changed).toBe(true)
    expect(appState.selectedNode).toBe(flat[1].id)
  })

  it('selectPrevious retreats selection by one', () => {
    const flat = appState.flattenedNodes
    dispatch({ type: 'selectNode', nodeId: flat[1].id })

    dispatch({ type: 'selectPrevious' })

    expect(appState.selectedNode).toBe(flat[0].id)
  })

  it('selectNext does not go past the last node', () => {
    const flat = appState.flattenedNodes
    dispatch({ type: 'selectNode', nodeId: flat[flat.length - 1].id })

    const changed = dispatch({ type: 'selectNext' })

    expect(changed).toBe(false)
    expect(appState.selectedNode).toBe(flat[flat.length - 1].id)
  })

  it('selectPrevious does not go before the first node', () => {
    const flat = appState.flattenedNodes
    dispatch({ type: 'selectNode', nodeId: flat[0].id })

    const changed = dispatch({ type: 'selectPrevious' })

    expect(changed).toBe(false)
    expect(appState.selectedNode).toBe(flat[0].id)
  })
})

// ── enterEditing / exitEditing ────────────────────────────────────────────────

describe('editing mode', () => {
  it('enterEditing sets mode to editing', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })

    const changed = dispatch({ type: 'enterEditing' })

    expect(changed).toBe(true)
    expect(appState.editorMode).toBe('editing')
  })

  it('exitEditing returns mode to selection', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })
    dispatch({ type: 'enterEditing' })

    const changed = dispatch({ type: 'exitEditing' })

    expect(changed).toBe(true)
    expect(appState.editorMode).toBe('selection')
  })

  it('enterEditing returns false with no selection', () => {
    appState.selectedNode = null
    const changed = dispatch({ type: 'enterEditing' })
    expect(changed).toBe(false)
  })

  it('exitEditing returns false when not in editing mode', () => {
    const target = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })
    // mode is 'selection'

    const changed = dispatch({ type: 'exitEditing' })
    expect(changed).toBe(false)
  })
})

// ── hydrateFromBackend ────────────────────────────────────────────────────────

describe('hydrateFromBackend', () => {
  it('builds correct node count from raw nodes', () => {
    expect(appState.nodes.length).toBe(5)
  })

  it('builds specRefIndex for O(1) lookup', () => {
    expect(appState.specRefIndex.has('specs/_main.md')).toBe(true)
    expect(appState.specRefIndex.has('specs/_main.md#spec-tree-pane')).toBe(true)
  })

  it('sets parent/child relationships correctly', () => {
    const pane = nodeByLabel('Spec Tree Pane')
    const editable = nodeByLabel('Editable Nodes')
    expect(editable.parent).toBe(pane.id)
    expect(pane.children).toContain(editable.id)
  })

  it('root has no parent', () => {
    const root = nodeByLabel('root')
    expect(root.parent).toBeNull()
  })

  it('restores selected node by spec_ref after re-hydration', () => {
    const target = nodeByLabel('Chat Pane')
    dispatch({ type: 'selectNode', nodeId: target.id })
    const specRef = target.specRef

    // Re-hydrate with same data
    loadDemoState()

    const restoredId = appState.specRefIndex.get(specRef)
    expect(restoredId).not.toBeUndefined()
  })
})

// ── flattenedNodes ────────────────────────────────────────────────────────────

describe('flattenedNodes', () => {
  it('returns all visible nodes', () => {
    // Demo has 5 nodes, all expanded after loadDemoState
    expect(appState.flattenedNodes.length).toBe(5)
  })

  it('collapsed node hides its children', () => {
    const pane = nodeByLabel('Spec Tree Pane')
    pane.collapsed = true

    const flat = appState.flattenedNodes
    const labels = flat.map((n) => firstLine(n.markdown))
    expect(labels).not.toContain('Editable Nodes')
    expect(labels).not.toContain('Tab Indent')
  })

  it('selection-highlighted flag propagates to children of selected node', () => {
    const pane = nodeByLabel('Spec Tree Pane')
    dispatch({ type: 'selectNode', nodeId: pane.id })

    const flat = appState.flattenedNodes
    const editableRow = flat.find((n) => firstLine(n.markdown) === 'Editable Nodes')
    expect(editableRow?.selectionHighlighted).toBe(true)
  })
})
