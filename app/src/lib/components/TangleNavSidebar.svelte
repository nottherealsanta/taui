<script lang="ts">
  import TangleNavItem from '$components/TangleNavItem.svelte'
  import ContextMenu from '$components/ContextMenu.svelte'
  import type { MenuItem } from '$components/ContextMenu.svelte'
  import InlineCreateInput from '$components/InlineCreateInput.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { backendClient } from '$services/backend-client'
  import type { TangleNavFolderItem, TangleNavHeadingItem, TangleNavItemType } from '$types/tangle-nav'
  import { basenameWithoutMarkdown, commonLeadingSegments, formatPathSegment, markdownLineLabel, tangleRefToFilePath } from '$lib/utils/tangles'

  let collapsedKeys = $state(new Set<string>())

  const activeFilePath = $derived(tabStore.activeTab?.filePath ?? null)
  const selectedFilePath = $derived.by(() => {
    if (appState.selectedNode === null) return null
    return tangleRefToFilePath(appState.nodes[appState.selectedNode]?.specRef ?? '')
  })

  function topLevelNodeIdsForFile(filePath: string): number[] {
    const result: number[] = []
    for (const node of appState.nodes) {
      if (tangleRefToFilePath(node.specRef) !== filePath) continue
      if (node.markdown.trim() === '' && node.children.length === 0) continue
      const parentId = node.parent
      if (parentId === null) {
        result.push(node.id)
        continue
      }
      const parentFilePath = tangleRefToFilePath(appState.nodes[parentId]?.specRef ?? '')
      if (parentFilePath !== filePath) {
        result.push(node.id)
      }
    }
    return result
  }

  function fileHeadingItem(filePath: string): TangleNavHeadingItem | null {
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
    const filePaths = [...new Set(appState.nodes.map((node) => tangleRefToFilePath(node.specRef)).filter(Boolean))]
    const commonRoot = commonLeadingSegments(filePaths)
    const root: TangleNavFolderItem = {
      kind: 'folder',
      key: 'root',
      label: 'root',
      children: [],
    }

    const folderIndex = new Map<string, TangleNavFolderItem>()
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

  function handleSelect(_item: TangleNavHeadingItem) {
    // Selection is handled in the child item before file open.
  }

  // ── Context menu state ─────────────────────────────────────────────────────
  let ctxMenu: { x: number; y: number; items: MenuItem[] } | null = $state(null)
  let pendingCreate: { dirPath: string; isDir: boolean } | null = $state(null)

  function resolveItemDirPath(item: TangleNavItemType): string {
    if (item.kind === 'folder') {
      // Extract real path from the key: "folder:root/segment1/segment2"
      const keyPath = item.key.replace(/^folder:/, '')
      // Remove leading 'root' and rejoin with the common root
      const segs = keyPath.split('/').slice(1) // drop 'root'
      const filePaths = [...new Set(appState.nodes.map((n) => tangleRefToFilePath(n.specRef)).filter(Boolean))]
      const commonRoot = commonLeadingSegments(filePaths)
      return [...commonRoot, ...segs].join('/')
    }
    // For heading items, use the parent directory of the file
    const fp = item.filePath
    const lastSlash = fp.lastIndexOf('/')
    return lastSlash > 0 ? fp.substring(0, lastSlash) : ''
  }

  function handleItemContextMenu(e: MouseEvent, item: TangleNavItemType) {
    e.preventDefault()
    e.stopPropagation()
    const dirPath = resolveItemDirPath(item)

    if (item.kind === 'folder') {
      const isCollapsed = collapsedKeys.has(item.key)
      ctxMenu = {
        x: e.clientX,
        y: e.clientY,
        items: [
          { label: isCollapsed ? 'Expand Folder' : 'Collapse Folder', action: () => toggleKey(item.key) },
          { separator: true },
          { label: 'New File', action: () => startCreate(dirPath, false) },
          { label: 'New Folder', action: () => startCreate(dirPath, true) },
          { separator: true },
          { label: 'Copy Path', action: () => void navigator.clipboard?.writeText(dirPath) },
        ],
      }
      return
    }

    const filePath = item.filePath
    const parentPath = dirPath
    ctxMenu = {
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: 'Open File', action: () => void tabStore.openFile(filePath) },
        { separator: true },
        { label: 'New File', action: () => startCreate(parentPath, false) },
        { label: 'New Folder', action: () => startCreate(parentPath, true) },
        { separator: true },
        { label: 'Copy Path', action: () => void navigator.clipboard?.writeText(filePath) },
      ],
    }
  }

  function handleSidebarContextMenu(e: MouseEvent) {
    e.preventDefault()
    // Determine root dir for the specs
    const filePaths = [...new Set(appState.nodes.map((n) => tangleRefToFilePath(n.specRef)).filter(Boolean))]
    const rootDir = commonLeadingSegments(filePaths).join('/')
    ctxMenu = {
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: 'New File', action: () => startCreate(rootDir, false) },
        { label: 'New Folder', action: () => startCreate(rootDir, true) },
        { separator: true },
        {
          label: 'Refresh',
          action: async () => {
            const tree = await backendClient.getTreeDetailed()
            appState.hydrateFromBackend(tree.nodes)
          },
        },
      ],
    }
  }

  function startCreate(dirPath: string, isDir: boolean) {
    pendingCreate = { dirPath, isDir }
  }

  async function commitCreate(name: string) {
    if (!pendingCreate || !name.trim()) {
      pendingCreate = null
      return
    }
    const { dirPath, isDir } = pendingCreate
    const fullPath = dirPath ? `${dirPath}/${name}` : name
    try {
      if (isDir) {
        await backendClient.createDir(fullPath)
      } else {
        // Create a new spec markdown file with a heading
        const baseName = name.replace(/\.md$/i, '')
        const fileName = name.endsWith('.md') ? name : `${name}.md`
        const filePath = dirPath ? `${dirPath}/${fileName}` : fileName
        await backendClient.writeFile(filePath, `# ${baseName}\n`)
        // Refresh the spec tree so the new file appears
        const tree = await backendClient.getTreeDetailed()
        appState.hydrateFromBackend(tree.nodes)
        // Open the new file
        await tabStore.openFile(filePath)
      }
    } catch (err) {
      console.error('[tangle-nav] Failed to create:', err)
    } finally {
      pendingCreate = null
    }
  }

  function cancelCreate() {
    pendingCreate = null
  }
</script>

<aside class="tangle-nav-sidebar">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="sidebar-content" oncontextmenu={handleSidebarContextMenu}>
    {#if pendingCreate}
      <InlineCreateInput
        isDir={pendingCreate.isDir}
        depth={0}
        oncommit={commitCreate}
        oncancel={cancelCreate}
      />
    {/if}
    {#if navItems.length === 0 && !pendingCreate}
      <div class="empty-state">No spec content loaded</div>
    {:else}
      {#each navItems as item (item.key)}
        <TangleNavItem
          {item}
          {collapsedKeys}
          {activeFilePath}
          {selectedFilePath}
          ontoggle={toggleKey}
          onselect={handleSelect}
          oncontextmenu={handleItemContextMenu}
        />
      {/each}
    {/if}
  </div>
</aside>

{#if ctxMenu}
  <ContextMenu
    x={ctxMenu.x}
    y={ctxMenu.y}
    items={ctxMenu.items}
    onclose={() => { ctxMenu = null }}
  />
{/if}

<style lang="postcss">
  .tangle-nav-sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background-color: var(--bg-surface);
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
