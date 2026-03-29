/**
 * Tab management store — manages open editor tabs, active tab,
 * dirty state, and content caching.
 *
 * Uses Svelte 5 $state runes for fine-grained reactivity.
 * Persists open tabs to localStorage for session restoration.
 */

import type { OpenTab } from '$types/index'
import { backendClient } from '$services/backend-client'
import { appState } from '$stores/app-state.svelte'
import { deriveSpecTitle, specRefToFilePath } from '$lib/utils/specs'

const STORAGE_KEY = 'taui-open-tabs'
const ACTIVE_TAB_KEY = 'taui-active-tab-file'

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
      this._persistState()
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

    const title = deriveSpecTitle(filePath, content, frontmatter)
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
    this._persistState()
  }

  /**
   * Close a tab by ID.
   */
  closeTab(tabId: string): void {
    const index = this.tabs.findIndex((t) => t.id === tabId)
    if (index === -1) return

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
    this._persistState()
  }

  /**
   * Close all tabs except the given one.
   */
  closeOtherTabs(tabId: string): void {
    this.tabs = this.tabs.filter((t) => t.id === tabId)
    this.activeTabId = tabId
    this._persistState()
  }

  /**
   * Close all tabs.
   */
  closeAllTabs(): void {
    this.tabs = []
    this.activeTabId = null
    this._persistState()
  }

  /**
   * Set the active tab.
   */
  setActiveTab(tabId: string): void {
    const tab = this.tabs.find((t) => t.id === tabId)
    if (tab) {
      this.activeTabId = tabId
      this._selectNodeForFile(tab.filePath)
      this._persistState()
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
      tab.title = deriveSpecTitle(tab.filePath, content, tab.frontmatter)
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
      await backendClient.writeFile(tab.filePath, tab.content)
      tab.isDirty = false
    } catch (err) {
      console.error(`[tabs] Failed to save: ${tab.filePath}`, err)
    }
  }

  /**
   * Restore tabs from localStorage.
   */
  restoreSession(): void {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      const activeFilePath = localStorage.getItem(ACTIVE_TAB_KEY)
      if (stored) {
        const paths = JSON.parse(stored) as string[]
        void this._restoreSessionAsync(paths, activeFilePath)
      }
    } catch {
      // ignore
    }
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
    this._persistState()
  }

  // ── Private ──────────────────────────────────────────────────────────────

  private _persistState(): void {
    try {
      const paths = this.tabs.map((t) => t.filePath)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(paths))
      const activeFilePath = this.activeTab?.filePath
      if (activeFilePath) {
        localStorage.setItem(ACTIVE_TAB_KEY, activeFilePath)
      }
    } catch {
      // ignore
    }
  }

  private async _restoreSessionAsync(paths: string[], activeFilePath: string | null): Promise<void> {
    // Wait for backend connection before attempting to read files
    if (appState.connectionState !== 'ready') {
      await new Promise<void>((resolve) => {
        const check = () => {
          if (appState.connectionState === 'ready') {
            resolve()
          } else if (typeof appState.connectionState === 'object' && 'error' in appState.connectionState) {
            resolve() // Give up waiting on error
          } else {
            setTimeout(check, 50)
          }
        }
        check()
      })
    }

    for (const path of paths) {
      await this.openFile(path)
    }

    if (!activeFilePath) return
    const activeTab = this.tabs.find((tab) => tab.filePath === activeFilePath)
    if (activeTab) {
      this.activeTabId = activeTab.id
      this._selectNodeForFile(activeTab.filePath)
      this._persistState()
    }
  }

  private _selectNodeForFile(filePath: string): void {
    const selectedId = appState.selectedNode
    if (selectedId !== null) {
      const selectedPath = specRefToFilePath(appState.nodes[selectedId]?.specRef ?? '')
      if (selectedPath === filePath) return
    }

    const matchingNode = appState.nodes.find((node) => specRefToFilePath(node.specRef) === filePath)
    if (matchingNode) {
      appState.setSelected(matchingNode.id)
    }
  }
}

export const tabStore: TabStore = import.meta.hot?.data?.tabStore ?? new TabStore()
if (import.meta.hot) {
  import.meta.hot.data.tabStore = tabStore
}
