<script lang="ts">
  import SpecNavItem from '$components/SpecNavItem.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import type { SpecNavFolderItem, SpecNavHeadingItem } from '$types/spec-nav'
  import { basenameWithoutMarkdown, commonLeadingSegments, formatPathSegment, markdownLineLabel, specRefToFilePath } from '$lib/utils/specs'

  const STORAGE_KEY = 'taui-spec-nav-collapsed'

  let collapsedKeys = $state(new Set<string>())

  const activeFilePath = $derived(tabStore.activeTab?.filePath ?? null)
  const selectedFilePath = $derived.by(() => {
    if (appState.selectedNode === null) return null
    return specRefToFilePath(appState.nodes[appState.selectedNode]?.specRef ?? '')
  })

  function loadCollapsedState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as string[]
      collapsedKeys = new Set(parsed)
    } catch {
      collapsedKeys = new Set()
    }
  }

  loadCollapsedState()

  $effect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsedKeys]))
    } catch {
      // ignore persistence failures
    }
  })

  function topLevelNodeIdsForFile(filePath: string): number[] {
    const result: number[] = []
    for (const node of appState.nodes) {
      if (specRefToFilePath(node.specRef) !== filePath) continue
      if (node.markdown.trim() === '' && node.children.length === 0) continue
      const parentId = node.parent
      if (parentId === null) {
        result.push(node.id)
        continue
      }
      const parentFilePath = specRefToFilePath(appState.nodes[parentId]?.specRef ?? '')
      if (parentFilePath !== filePath) {
        result.push(node.id)
      }
    }
    return result
  }

  function fileHeadingItem(filePath: string): SpecNavHeadingItem | null {
    const topLevelNodes = topLevelNodeIdsForFile(filePath)
    const primaryNodeId = topLevelNodes[0]
    const primaryNode = primaryNodeId !== undefined ? appState.nodes[primaryNodeId] : null
    const label = primaryNode
      ? markdownLineLabel(primaryNode.markdown)
      : formatPathSegment(basenameWithoutMarkdown(filePath))

    if (!label) return null

    return {
      kind: 'heading',
      key: `heading-file:${filePath}`,
      label,
      filePath,
      nodeId: primaryNodeId ?? -1,
      children: [],
      collapsible: false,
    }
  }

  const navItems = $derived.by(() => {
    const filePaths = [...new Set(appState.nodes.map((node) => specRefToFilePath(node.specRef)).filter(Boolean))]
    const commonRoot = commonLeadingSegments(filePaths)
    const root: SpecNavFolderItem = {
      kind: 'folder',
      key: 'root',
      label: 'root',
      children: [],
    }

    const folderIndex = new Map<string, SpecNavFolderItem>()
    folderIndex.set('root', root)

    for (const filePath of filePaths) {
      const relativeSegments = filePath.split('/').filter(Boolean).slice(commonRoot.length)
      const folderSegments = relativeSegments.slice(0, -1)
      let currentFolder = root
      let currentPath = 'root'

      for (const segment of folderSegments) {
        currentPath = `${currentPath}/${segment}`
        let folder = folderIndex.get(currentPath)
        if (!folder) {
          folder = {
            kind: 'folder',
            key: `folder:${currentPath}`,
            label: formatPathSegment(segment),
            children: [],
          }
          folderIndex.set(currentPath, folder)
          currentFolder.children = [...currentFolder.children, folder]
        }
        currentFolder = folder
      }

      const headingItem = fileHeadingItem(filePath)
      if (headingItem) {
        currentFolder.children = [...currentFolder.children, headingItem]
      }
    }

    return root.children
  })

  function toggleKey(key: string) {
    const next = new Set(collapsedKeys)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
    }
    collapsedKeys = next
  }

  function handleSelect(_item: SpecNavHeadingItem) {
    // Selection is handled in the child item before file open.
  }
</script>

<aside class="spec-nav-sidebar">
  <div class="sidebar-header">
    <span class="header-label">Specs</span>
  </div>

  <div class="sidebar-content">
    {#if navItems.length === 0}
      <div class="empty-state">No spec content loaded</div>
    {:else}
      {#each navItems as item (item.key)}
        <SpecNavItem
          {item}
          {collapsedKeys}
          {activeFilePath}
          {selectedFilePath}
          ontoggle={toggleKey}
          onselect={handleSelect}
        />
      {/each}
    {/if}
  </div>
</aside>

<style lang="postcss">
  .spec-nav-sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background-color: var(--bg-surface);
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 34px;
    padding: 0 10px;
    border-bottom: 1px solid var(--border-variant);
    flex-shrink: 0;
  }

  .header-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-muted);
  }

  .sidebar-content {
    flex: 1;
    overflow: auto;
    padding: 6px 4px 12px;
  }

  .empty-state {
    padding: 16px 12px;
    color: var(--fg-muted);
    font-size: 12px;
  }
</style>