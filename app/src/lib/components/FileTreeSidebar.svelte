<!--
  FileTreeSidebar.svelte — Left sidebar file/folder browser.

  Displays a recursive file tree with:
  - "SPEC" header with collapse/expand all buttons
  - Folder expand/collapse
  - File click to open in center editor tab
  - Lazy-loads directory contents via fs/listDir
-->
<script lang="ts">
  import { onMount } from 'svelte'
  import { fileTree } from '$stores/file-tree.svelte'
  import FileTreeItem from '$components/FileTreeItem.svelte'
  import ContextMenu from '$components/ContextMenu.svelte'
  import InlineCreateInput from '$components/InlineCreateInput.svelte'
  import type { MenuItem } from '$components/ContextMenu.svelte'

  // Load root directory on mount
  onMount(() => {
    fileTree.loadDir(fileTree.rootPath)
  })

  const rootEntries = $derived(fileTree.getChildren(fileTree.rootPath))
  const isLoading = $derived(fileTree.isLoading(fileTree.rootPath))

  // Check if the pending creation is at root level
  const pendingAtRoot = $derived(
    fileTree.pendingCreation?.parentPath === fileTree.rootPath ? fileTree.pendingCreation : null
  )

  let contextMenu: { x: number; y: number } | null = $state(null)

  function handleRefresh() {
    fileTree.refresh()
  }

  function handleCollapseAll() {
    fileTree.expandedDirs = new Set()
  }

  function handleContextMenu(e: MouseEvent) {
    e.preventDefault()
    contextMenu = { x: e.clientX, y: e.clientY }
  }

  function getContextMenuItems(): MenuItem[] {
    return [
      { label: 'New File', action: () => fileTree.startCreation(fileTree.rootPath, false) },
      { label: 'New Folder', action: () => fileTree.startCreation(fileTree.rootPath, true) },
    ]
  }

  function handleCommitCreate(name: string) {
    fileTree.commitCreation(name)
  }

  function handleCancelCreate() {
    fileTree.cancelCreation()
  }
</script>

<aside class="file-tree-sidebar">
  <div class="sidebar-header">
    <span class="header-label">SPEC</span>
    <div class="header-actions">
      <button
        class="action-btn"
        onclick={handleRefresh}
        title="Refresh"
        aria-label="Refresh file tree"
      >↻</button>
      <button
        class="action-btn"
        onclick={handleCollapseAll}
        title="Collapse all"
        aria-label="Collapse all folders"
      >⊟</button>
    </div>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="tree-content" oncontextmenu={handleContextMenu}>
    {#if isLoading && rootEntries.length === 0}
      <div class="loading-state">Loading…</div>
    {:else if rootEntries.length === 0 && !pendingAtRoot}
      <div class="empty-state">No files found</div>
    {:else}
      {#if pendingAtRoot}
        <InlineCreateInput
          isDir={pendingAtRoot.isDir}
          depth={0}
          oncommit={handleCommitCreate}
          oncancel={handleCancelCreate}
        />
      {/if}
      {#each rootEntries as entry (entry.path)}
        <FileTreeItem {entry} depth={0} />
      {/each}
    {/if}
  </div>
</aside>

{#if contextMenu}
  <ContextMenu
    x={contextMenu.x}
    y={contextMenu.y}
    items={getContextMenuItems()}
    onclose={() => { contextMenu = null }}
  />
{/if}

<style lang="postcss">
  .file-tree-sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    background-color: var(--bg-surface);
    overflow: hidden;
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-variant);
    flex-shrink: 0;
  }

  .header-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .header-actions {
    display: flex;
    gap: 2px;
  }

  .action-btn {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
    padding: 2px 4px;
    border-radius: 3px;
    line-height: 1;
    transition: all 0.15s;
  }

  .action-btn:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .tree-content {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 4px 0;
  }

  .loading-state,
  .empty-state {
    padding: 16px 12px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
  }
</style>
