<!--
  4.2 TreeRow.svelte
  A single row in the spec tree: indent, chevron, status, agent dot, content.
  When editing, the InlineEditor replaces the label in-place within the row.
-->
<script lang="ts">
  import type { FlatNode } from '$types/index'
  import StatusBadge from './StatusBadge.svelte'
  import InlineEditor from './InlineEditor.svelte'
  import { indentPx, depthToRowStyle } from '$types/typography'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'

  interface Props {
    node: FlatNode
    onclick?: (node: FlatNode) => void
    ondblclick?: (node: FlatNode) => void
  }
  const { node, onclick, ondblclick }: Props = $props()

  const isSelected = $derived(node.selected)
  const isEditing = $derived(isSelected && appState.editorMode === 'editing')

  const rowStyle = $derived(depthToRowStyle(node.depth))
  const indent = $derived(indentPx(node.depth))

  // Look up live values from the source node
  const status = $derived(appState.nodes[node.id]?.status ?? null)
  const specRef = $derived(appState.nodes[node.id]?.specRef ?? '')
  const currentMarkdown = $derived(appState.nodes[node.id]?.markdown ?? node.markdown)

  function handleClick() {
    dispatch({ type: 'selectNode', nodeId: node.id })
    onclick?.(node)
  }

  function handleDblClick() {
    dispatch({ type: 'selectNode', nodeId: node.id })
    dispatch({ type: 'enterEditing' })
    ondblclick?.(node)
  }

  function handleChevronClick(e: MouseEvent) {
    e.stopPropagation()
    if (isSelected) {
      dispatch({ type: 'toggleCollapse' })
    } else {
      dispatch({ type: 'selectNode', nodeId: node.id })
      dispatch({ type: 'toggleCollapse' })
    }
  }

  function handleAgentDotClick(e: MouseEvent) {
    e.stopPropagation()
    if (node.agentId) {
      appState.detailAgentId = appState.detailAgentId === node.agentId ? null : node.agentId
    }
  }

  // First non-empty line for the row label — strip leading heading markers (#)
  const label = $derived(node.markdown.split('\n')[0].trim().replace(/^#+\s*/, '') || '…')
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="tree-row"
  class:selected={isSelected}
  class:highlighted={node.selectionHighlighted && !isSelected}
  class:editing={isEditing}
  class:locked={node.locked}
  style:padding-left="{indent + 4}px"
  onclick={isEditing ? null : handleClick}
  ondblclick={isEditing ? null : handleDblClick}
  role="treeitem"
  aria-selected={isSelected}
  data-node-id={node.id}
>
  <!-- Chevron / leaf indicator -->
  <span
    class="chevron"
    class:has-children={node.hasChildren}
    class:collapsed={node.collapsed}
    onclick={node.hasChildren ? handleChevronClick : undefined}
    role={node.hasChildren ? 'button' : undefined}
    aria-label={node.hasChildren ? (node.collapsed ? 'expand' : 'collapse') : undefined}
  >
    {#if node.hasChildren}
      {node.collapsed ? '▶' : '▼'}
    {:else}
      <span class="leaf-dot"></span>
    {/if}
  </span>

  <!-- Row content: InlineEditor when editing, label otherwise -->
  {#if isEditing}
    <InlineEditor
      nodeId={node.id}
      {specRef}
      initialMarkdown={currentMarkdown}
    />
  {:else}
    <span
      class="row-label"
      style:font-size={rowStyle.fontSize}
      style:font-weight={rowStyle.fontWeight}
    >{label}</span>
  {/if}

  <!-- Right-side indicators (hidden while editing to give editor full width) -->
  {#if !isEditing}
  <span class="indicators">
    {#if node.hasQuestion}
      <span class="indicator question-dot" title="Pending question">?</span>
    {/if}
    {#if node.agentId}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <span
        class="indicator agent-dot"
        class:detail-open={appState.detailAgentId === node.agentId}
        title="Agent active: {node.agentId} (click to view)"
        onclick={handleAgentDotClick}
        role="button"
        tabindex="-1"
      ></span>
    {/if}
    {#if node.locked}
      <span class="indicator lock-icon" title="Locked by agent">🔒</span>
    {/if}
    {#if status}
      <StatusBadge {status} />
    {/if}
  </span>
  {/if}
</div>

<style lang="postcss">
  .tree-row {
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 28px;
    height: auto;
    padding-right: 8px;
    cursor: pointer;
    border-radius: 4px;
    margin: 1px 4px;
    transition: background-color 0.1s;
    color: var(--fg-primary);
    position: relative;
  }

  .tree-row:hover { background-color: var(--element-hover); }
  .tree-row.selected { background-color: var(--element-selected); }
  .tree-row.highlighted { background-color: var(--element-bg); }
  .tree-row.editing {
    background-color: var(--element-selected);
    outline: 1px solid var(--fg-accent);
    align-items: flex-start;
    padding-top: 2px;
    padding-bottom: 2px;
    cursor: default;
  }
  .tree-row.locked { opacity: 0.7; }

  /* Chevron */
  .chevron {
    flex-shrink: 0;
    width: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 8px;
    color: var(--fg-muted);
  }
  .chevron.has-children { cursor: pointer; }
  .chevron.has-children:hover { color: var(--fg-primary); }

  .leaf-dot {
    display: inline-block;
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background-color: var(--border);
  }

  /* Label */
  .row-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    line-height: 1.3;
  }

  /* Indicators */
  .indicators {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }

  .indicator {
    display: flex;
    align-items: center;
    font-size: 10px;
  }

  .agent-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: var(--status-in-progress);
    animation: pulse 1.5s ease-in-out infinite;
    cursor: pointer;
    transition: outline 0.1s, transform 0.1s;
  }
  .agent-dot:hover { transform: scale(1.3); }
  .agent-dot.detail-open {
    outline: 2px solid var(--fg-accent);
    outline-offset: 1px;
    animation: none;
    opacity: 1;
  }

  .question-dot {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background-color: var(--status-warning);
    color: #000;
    font-weight: 700;
    font-size: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

  .lock-icon { font-size: 10px; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
