<!--
  4.3 TreeView.svelte
  Virtual-scrolled list of TreeRow components.
  Handles keyboard navigation (up/down/tab/shift-tab/enter/escape/f2).
-->
<script lang="ts">
  import { onMount, tick } from 'svelte'
  import type { FlatNode } from '$types/index'
  import TreeRow from './TreeRow.svelte'
  import CodeRefRow from './CodeRefRow.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'
  import { backendClient } from '$services/backend-client'

  interface Props {
    onenterEditing?: (nodeId: number) => void
    onshowCodeRef?: (
      filePath: string,
      content: string,
      lineStart: number | null,
      lineEnd: number | null,
      language?: string,
      specRef?: string | null,
      truncated?: boolean,
      previewStart?: number | null,
      previewEnd?: number | null,
    ) => void
  }
  const { onenterEditing, onshowCodeRef }: Props = $props()

  const ROW_HEIGHT = 30  // px — used for virtual scrolling
  const OVERSCAN = 5     // extra rows above/below viewport

  let containerEl: HTMLElement | undefined = $state()
  let scrollTop = $state(0)
  let containerHeight = $state(600)

  const nodes = $derived(appState.flattenedTreeNodes)

  // When editing, the selected row expands beyond ROW_HEIGHT.
  const editingNodeId = $derived(
    appState.editorMode === 'editing' ? appState.selectedNode : null
  )

  // Virtual window
  const startIndex = $derived(Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN))
  const visibleCount = $derived(Math.ceil(containerHeight / ROW_HEIGHT) + OVERSCAN * 2)
  const endIndex = $derived(Math.min(nodes.length, startIndex + visibleCount))
  const visibleNodes = $derived(nodes.slice(startIndex, endIndex))
  const totalHeight = $derived(nodes.length * ROW_HEIGHT)
  const offsetY = $derived(startIndex * ROW_HEIGHT)

  // Auto-scroll selected node into view
  $effect(() => {
    const selectedId = appState.selectedNode
    if (selectedId === null || !containerEl) return
    const idx = nodes.findIndex((n) => n.id === selectedId)
    if (idx === -1) return
    const rowTop = idx * ROW_HEIGHT
    const rowBottom = rowTop + ROW_HEIGHT
    if (rowTop < scrollTop) {
      containerEl.scrollTop = rowTop
    } else if (rowBottom > scrollTop + containerHeight) {
      containerEl.scrollTop = rowBottom - containerHeight
    }
  })

  // Resize observer
  onMount(() => {
    if (!containerEl) return
    const obs = new ResizeObserver((entries) => {
      containerHeight = entries[0]?.contentRect.height ?? containerHeight
    })
    obs.observe(containerEl)
    return () => obs.disconnect()
  })

  function handleScroll(e: Event) {
    scrollTop = (e.target as HTMLElement).scrollTop
  }

  // ── Keyboard navigation ────────────────────────────────────────────────────
  function handleKeyDown(e: KeyboardEvent) {
    // When editing mode is active, most keys go to the editor; only Escape escapes.
    if (appState.editorMode === 'editing') {
      if (e.key === 'Escape') {
        e.preventDefault()
        dispatch({ type: 'exitEditing' })
      }
      return
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        dispatch({ type: 'selectNext' })
        break
      case 'ArrowUp':
        e.preventDefault()
        dispatch({ type: 'selectPrevious' })
        break
      case 'Tab':
        e.preventDefault()
        if (e.shiftKey) {
          _outdent()
        } else {
          _indent()
        }
        break
      case 'Enter':
        e.preventDefault()
        // In selection mode: Enter = add sibling node (structural edit).
        _addSibling()
        break
      case 'F2':
        e.preventDefault()
        // F2 = enter inline editing mode.
        if (appState.selectedNode !== null) {
          dispatch({ type: 'enterEditing' })
          onenterEditing?.(appState.selectedNode)
        }
        break
      case 'Escape':
        e.preventDefault()
        appState.editorMode = 'selection'
        break
      case ' ':
        e.preventDefault()
        dispatch({ type: 'toggleCollapse' })
        break
    }
  }

  async function _indent() {
    const specRef = appState.selectedSpecRef
    dispatch({ type: 'indentNode' })
    if (specRef) {
      try { await backendClient.indentNode(specRef) } catch { /* local-only fallback */ }
    }
  }

  async function _outdent() {
    const specRef = appState.selectedSpecRef
    dispatch({ type: 'outdentNode' })
    if (specRef) {
      try { await backendClient.outdentNode(specRef) } catch { /* local-only fallback */ }
    }
  }

  async function _addSibling() {
    const specRef = appState.selectedSpecRef
    // Optimistically add locally, then sync to backend.
    dispatch({ type: 'addSiblingNode' })
    onenterEditing?.(appState.selectedNode!)
    if (specRef && !specRef.startsWith('local/')) {
      try {
        const result = await backendClient.createSiblingNode(specRef)
        // Update the temp local node with the real spec_ref from backend.
        const newId = appState.selectedNode
        if (newId !== null && result.node) {
          const node = appState.nodes[newId]
          if (node && node.specRef.startsWith('local/')) {
            appState.specRefIndex.delete(node.specRef)
            node.specRef = result.node.spec_ref
            appState.specRefIndex.set(node.specRef, newId)
          }
        }
      } catch { /* local-only fallback */ }
    }
  }
</script>

<!-- svelte-ignore a11y_interactive_supports_focus -->
<div
  class="tree-view"
  role="tree"
  tabindex="0"
  onkeydown={handleKeyDown}
  onscroll={handleScroll}
  bind:this={containerEl}
>
  <!-- Virtual scroll spacer -->
  <div class="virtual-spacer" style:height="{totalHeight}px">
    <div class="visible-rows" style:transform="translateY({offsetY}px)">
      {#each visibleNodes as node (node.id)}
        <div
          style:min-height="{ROW_HEIGHT}px"
          style:height={node.id === editingNodeId ? 'auto' : `${ROW_HEIGHT}px`}
        >
          {#if node.kind === 'codeRef'}
            <CodeRefRow {node} {onshowCodeRef} />
          {:else}
            <TreeRow {node} />
          {/if}
        </div>
      {/each}
    </div>
  </div>

  {#if nodes.length === 0}
    <div class="empty-state">
      <p>No spec nodes loaded.</p>
      <p class="hint">Connect to the backend to load the spec tree.</p>
    </div>
  {/if}
</div>

<style lang="postcss">
  .tree-view {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    outline: none;
    padding: 4px 0;
  }
  .tree-view:focus-visible { outline: none; }

  .virtual-spacer {
    position: relative;
    width: 100%;
    max-width: 820px;
    margin: 0 auto;
  }

  .visible-rows {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    will-change: transform;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--fg-muted);
    font-size: 13px;
    gap: 6px;
  }
  .empty-state p { margin: 0; }
  .hint { font-size: 11px; }
</style>
