/**
 * Tab management store — manages open editor tabs, active tab,
 * dirty state, and content caching.
 *
 * Uses Svelte 5 $state runes for fine-grained reactivity.
 * Mirrors open tabs from backend snapshot for session restoration.
 */

import type { OpenTab } from '$types/index'
import { backendClient } from '$services/backend-client'
import { appState } from '$stores/app-state.svelte'
import { fileTree } from '$stores/file-tree.svelte'
import { deriveTangleTitle, tangleRefToFilePath } from '$lib/utils/tangles'

class TabStore {
  tabs: OpenTab[] = $state([])
  activeTabId: string | null = $state(null)

  // ── Derived ──────────────────────────────────────────────────────────────

  get activeTab(): OpenTab | null {
    if (this.activeTabId === null) return null
    return this.tabs.find((t) => t.id === this.activeTabId) ?? null
  }

  get hasDirtyTabs(): boolean {
    return this.tabs.some((t) => t.isDirty)
  }

  // ── Methods ──────────────────────────────────────────────────────────────

  /**
   * Open a file in a new tab (or switch to existing tab if already open).
   */
  async openFile(filePath: string): Promise<void> {
    // Check if already open
    const existing = this.tabs.find((t) => t.filePath === filePath)
    if (existing) {
      this.activeTabId = existing.id
      this._selectNodeForFile(filePath)
      void this._syncFileTreeSelection(filePath)
      void backendClient.uiSetActiveTab(filePath)
      return
    }

    // Load file content from backend
    let content = ''
    let frontmatter: Record<string, unknown> | undefined
    try {
      const result = await backendClient.readFile(filePath)
      content = result.content
      frontmatter = result.frontmatter ?? undefined
    } catch (err) {
      console.error(`[tabs] Failed to read file: ${filePath}`, err)
      content = ''
    }

    const title = deriveTangleTitle(filePath, content, frontmatter)
    const id = `tab-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

    const tab: OpenTab = {
      id,
      filePath,
      title,
      isDirty: false,
      content,
      frontmatter,
    }

    this.tabs = [...this.tabs, tab]
    this.activeTabId = id
    this._selectNodeForFile(filePath)
    void this._syncFileTreeSelection(filePath)
    await backendClient.uiOpenTab(filePath)
  }

  /**
   * Close a tab by ID.
   */
  async closeTab(tabId: string): Promise<void> {
    const index = this.tabs.findIndex((t) => t.id === tabId)
    if (index === -1) return

    const closed = this.tabs[index]

    this.tabs = this.tabs.filter((t) => t.id !== tabId)

    // If we closed the active tab, select an adjacent tab
    if (this.activeTabId === tabId) {
      if (this.tabs.length === 0) {
        this.activeTabId = null
      } else {
        const newIndex = Math.min(index, this.tabs.length - 1)
        this.activeTabId = this.tabs[newIndex].id
        this._selectNodeForFile(this.tabs[newIndex].filePath)
      }
    }
    await backendClient.uiCloseTab(closed.filePath)
  }

  /**
   * Close all tabs except the given one.
   */
  async closeOtherTabs(tabId: string): Promise<void> {
    const toClose = this.tabs.filter((t) => t.id !== tabId)
    this.tabs = this.tabs.filter((t) => t.id === tabId)
    this.activeTabId = tabId
    await Promise.all(toClose.map((tab) => backendClient.uiCloseTab(tab.filePath)))
  }

  /**
   * Close all tabs.
   */
  async closeAllTabs(): Promise<void> {
    const existing = [...this.tabs]
    this.tabs = []
    this.activeTabId = null
    await Promise.all(existing.map((tab) => backendClient.uiCloseTab(tab.filePath)))
  }

  /**
   * Set the active tab.
   */
  async setActiveTab(tabId: string): Promise<void> {
    const tab = this.tabs.find((t) => t.id === tabId)
    if (tab) {
      this.activeTabId = tabId
      this._selectNodeForFile(tab.filePath)
      void this._syncFileTreeSelection(tab.filePath)
      await backendClient.uiSetActiveTab(tab.filePath)
    }
  }

  /**
   * Mark a tab as dirty (unsaved changes).
   */
  markDirty(tabId: string): void {
    const tab = this.tabs.find((t) => t.id === tabId)
    if (tab) {
      tab.isDirty = true
    }
  }

  /**
   * Update tab content (from editor changes).
   */
  updateContent(tabId: string, content: string): void {
    const tab = this.tabs.find((t) => t.id === tabId)
    if (tab) {
      tab.content = content
      tab.title = deriveTangleTitle(tab.filePath, content, tab.frontmatter)
      tab.isDirty = true
    }
  }

  /**
   * Save the active tab's content to the backend.
   */
  async save(tabId?: string): Promise<void> {
    const id = tabId ?? this.activeTabId
    if (!id) return

    const tab = this.tabs.find((t) => t.id === id)
    if (!tab || !tab.isDirty) return

    try {
      await backendClient.uiSaveTab(tab.filePath, tab.content)
      tab.isDirty = false
    } catch (err) {
      console.error(`[tabs] Failed to save: ${tab.filePath}`, err)
    }
  }

  /**
   * Restore tabs from localStorage.
   */
  restoreSession(): void {
    // No-op: session now restored via ui.snapshot in connection.ts.
  }

  /**
   * Move a tab to a new position (drag reordering).
   */
  moveTab(fromIndex: number, toIndex: number): void {
    if (fromIndex === toIndex) return
    if (fromIndex < 0 || fromIndex >= this.tabs.length) return
    if (toIndex < 0 || toIndex >= this.tabs.length) return

    const tab = this.tabs[fromIndex]
    const next = [...this.tabs]
    next.splice(fromIndex, 1)
    next.splice(toIndex, 0, tab)
    this.tabs = next
  }

  // ── Private ──────────────────────────────────────────────────────────────

  applySnapshot(snapshot: { open?: string[]; active?: string }): void {
    const open = Array.isArray(snapshot.open) ? snapshot.open : []
    const active = typeof snapshot.active === 'string' ? snapshot.active : ''
    const prevByPath = new Map(this.tabs.map((t) => [t.filePath, t]))
    const next: OpenTab[] = []
    for (const path of open) {
      const existing = prevByPath.get(path)
      if (existing) {
        next.push(existing)
      } else {
        next.push({
          id: `tab-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          filePath: path,
          title: deriveTangleTitle(path, '', undefined),
          isDirty: false,
          content: '',
          frontmatter: undefined,
        })
      }
    }
    this.tabs = next
    const activeTab = this.tabs.find((t) => t.filePath === active) ?? this.tabs[0] ?? null
    this.activeTabId = activeTab?.id ?? null
    if (activeTab) {
      this._selectNodeForFile(activeTab.filePath)
      void this._syncFileTreeSelection(activeTab.filePath)
    }

    // Load file content for all restored tabs that have empty content.
    // applySnapshot creates placeholder tabs with content: '' — we need to
    // fetch the actual file content from the backend so editors aren't blank.
    void this._loadRestoredTabContent()
  }

  /**
   * Load file content for any tabs that were restored with empty content
   * (e.g. from session snapshot). Fetches all empty tabs in parallel.
   */
  private async _loadRestoredTabContent(): Promise<void> {
    const emptyTabs = this.tabs.filter((t) => t.content === '' && !t.isDirty)
    if (emptyTabs.length === 0) return

    await Promise.all(
      emptyTabs.map(async (tab) => {
        try {
          const result = await backendClient.readFile(tab.filePath)
          // Tab may have been closed while we were loading — check it still exists
          const current = this.tabs.find((t) => t.id === tab.id)
          if (current && current.content === '') {
            current.content = result.content
            current.frontmatter = result.frontmatter ?? undefined
            current.title = deriveTangleTitle(current.filePath, current.content, current.frontmatter)
          }
        } catch (err) {
          console.error(`[tabs] Failed to load restored tab content: ${tab.filePath}`, err)
        }
      }),
    )
  }

  private _selectNodeForFile(filePath: string): void {
    const selectedId = appState.selectedNode
    if (selectedId !== null) {
      const selectedPath = tangleRefToFilePath(appState.nodes[selectedId]?.specRef ?? '')
      if (selectedPath === filePath) return
    }

    const matchingNode = appState.nodes.find((node) => tangleRefToFilePath(node.specRef) === filePath)
    if (matchingNode) {
      appState.setSelected(matchingNode.id)
    }
  }

  private async _syncFileTreeSelection(filePath: string): Promise<void> {
    try {
      await fileTree.revealPath(filePath)
    } catch (err) {
      console.error(`[tabs] Failed to sync file tree selection: ${filePath}`, err)
    }
  }
}

export const tabStore: TabStore = import.meta.hot?.data?.tabStore ?? new TabStore()
if (import.meta.hot) {
  import.meta.hot.data.tabStore = tabStore
}
