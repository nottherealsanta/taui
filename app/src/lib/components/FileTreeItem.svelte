<!--
  FileTreeItem.svelte — Individual row in the file tree sidebar.

  Handles indent, icon, label, active/selected state.
  Supports folder expand/collapse and file click-to-open.
  Right-click context menu for creating new files/folders.
-->
<script lang="ts">
  import type { FileEntry } from '$types/index'
  import type { MenuItem } from '$components/ContextMenu.svelte'
  import { fileTree } from '$stores/file-tree.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import ContextMenu from '$components/ContextMenu.svelte'
  import InlineCreateInput from '$components/InlineCreateInput.svelte'

  interface Props {
    entry: FileEntry
    depth?: number
  }
  const { entry, depth = 0 }: Props = $props()

  const isExpanded = $derived(fileTree.isExpanded(entry.path))
  const isSelected = $derived(fileTree.selectedFile === entry.path)
  const isLoading = $derived(entry.isDir && fileTree.isLoading(entry.path))
  const children = $derived(entry.isDir ? fileTree.getChildren(entry.path) : [])

  // Check if the pending creation targets this directory
  const pendingHere = $derived(
    fileTree.pendingCreation?.parentPath === entry.path ? fileTree.pendingCreation : null
  )

  let contextMenu: { x: number; y: number } | null = $state(null)

  function handleClick() {
    if (entry.isDir) {
      fileTree.toggleDir(entry.path)
    } else {
      fileTree.selectFile(entry.path)
      tabStore.openFile(entry.path)
    }
  }

  function handleContextMenu(e: MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    contextMenu = { x: e.clientX, y: e.clientY }
  }

  function getContextMenuItems(): MenuItem[] {
    // For directories: "New File" and "New Folder" create inside this dir
    if (entry.isDir) {
      return [
        { label: 'New File', action: () => fileTree.startCreation(entry.path, false) },
        { label: 'New Folder', action: () => fileTree.startCreation(entry.path, true) },
      ]
    }
    // For files: create sibling in parent dir
    const parentPath = entry.path.includes('/') ? entry.path.substring(0, entry.path.lastIndexOf('/')) : ''
    return [
      { label: 'New File', action: () => fileTree.startCreation(parentPath, false) },
      { label: 'New Folder', action: () => fileTree.startCreation(parentPath, true) },
    ]
  }

  function handleCommitCreate(name: string) {
    fileTree.commitCreation(name)
  }

  function handleCancelCreate() {
    fileTree.cancelCreation()
  }

  function getFileIcon(entry: FileEntry): string {
    if (entry.isDir) {
      return isExpanded ? '▾' : '▸'
    }
    switch (entry.extension) {
      case 'md': return '📄'
      case 'ts':
      case 'tsx': return '🟦'
      case 'js':
      case 'jsx': return '🟨'
      case 'py': return '🐍'
      case 'json': return '{ }'
      case 'css': return '🎨'
      case 'svelte': return '🔥'
      case 'html': return '🌐'
      case 'yaml':
      case 'yml': return '📋'
      case 'toml': return '⚙'
      default: return '📄'
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="tree-item"
  class:selected={isSelected}
  class:directory={entry.isDir}
  style="padding-left: {12 + depth * 16}px"
  onclick={handleClick}
  oncontextmenu={handleContextMenu}
>
  <span class="icon" class:dir-icon={entry.isDir}>
    {getFileIcon(entry)}
  </span>
  <span class="label" class:dir-label={entry.isDir}>
    {entry.name}
  </span>
  {#if isLoading}
    <span class="loading-indicator">…</span>
  {/if}
</div>

{#if entry.isDir && isExpanded}
  {#if pendingHere}
    <InlineCreateInput
      isDir={pendingHere.isDir}
      depth={depth + 1}
      oncommit={handleCommitCreate}
      oncancel={handleCancelCreate}
    />
  {/if}
  {#each children as child (child.path)}
    <svelte:self entry={child} depth={depth + 1} />
  {/each}
{/if}

{#if contextMenu}
  <ContextMenu
    x={contextMenu.x}
    y={contextMenu.y}
    items={getContextMenuItems()}
    onclose={() => { contextMenu = null }}
  />
{/if}

<style lang="postcss">
  .tree-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    cursor: pointer;
    font-size: 12px;
    color: var(--fg-primary);
    transition: background-color 0.1s;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-height: 24px;
  }

  .tree-item:hover {
    background-color: var(--element-hover);
  }

  .tree-item.selected {
    background-color: var(--element-selected);
  }

  .icon {
    flex-shrink: 0;
    width: 16px;
    text-align: center;
    font-size: 11px;
    line-height: 1;
  }

  .dir-icon {
    color: var(--fg-muted);
    font-size: 10px;
  }

  .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dir-label {
    font-weight: 500;
  }

  .loading-indicator {
    color: var(--fg-muted);
    font-size: 10px;
    margin-left: auto;
    flex-shrink: 0;
  }
</style>
