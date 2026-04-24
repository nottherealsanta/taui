/**
 * File tree state store — manages directory listings, expanded state,
 * and selected file for the left sidebar.
 *
 * Uses Svelte 5 $state runes for fine-grained reactivity.
 */

import type { FileEntry } from '$types/index'
import { backendClient } from '$services/backend-client'
import { SvelteMap, SvelteSet } from 'svelte/reactivity'

type PendingCreation = {
  parentPath: string
  isDir: boolean
}

class FileTreeStore {
  /** Cached directory listings keyed by path. */
  entries: Map<string, FileEntry[]> = $state(new SvelteMap())

  /** Set of expanded directory paths. */
  expandedDirs: Set<string> = $state(new SvelteSet())

  /** Currently highlighted file path in the tree. */
  selectedFile: string | null = $state(null)

  /** Whether the left sidebar is collapsed. */
  sidebarCollapsed: boolean = $state(false)

  /** Loading state per directory. */
  loading: Set<string> = $state(new SvelteSet())

  /** Root path for the file tree (relative, usually '' or 'specs'). */
  rootPath: string = $state('')

  /** Pending inline creation (new file or folder). */
  pendingCreation: PendingCreation | null = $state(null)

  // ── Methods ──────────────────────────────────────────────────────────────

  /**
   * Load a directory's contents from the backend.
   * Caches the result in `entries`.
   */
  async loadDir(path: string): Promise<void> {
    if (this.loading.has(path)) return

    this.loading = new Set([...this.loading, path])
    try {
      const result = await backendClient.listDir(path)
      this.entries = new Map(this.entries).set(path, result.entries)
    } catch (err) {
      console.error(`[file-tree] Failed to load dir: ${path}`, err)
    } finally {
      const next = new Set(this.loading)
      next.delete(path)
      this.loading = next
    }
  }

  /**
   * Toggle a directory open/closed.
   * Loads contents on first expand.
   */
  async toggleDir(path: string): Promise<void> {
    if (this.expandedDirs.has(path)) {
      const next = new Set(this.expandedDirs)
      next.delete(path)
      this.expandedDirs = next
    } else {
      this.expandedDirs = new Set([...this.expandedDirs, path])
      // Load contents if not cached
      if (!this.entries.has(path)) {
        await this.loadDir(path)
      }
    }
  }

  /**
   * Select a file. Called when user clicks a file in the tree.
   */
  selectFile(path: string): void {
    this.selectedFile = path
  }

  /**
   * Refresh a directory listing from the backend.
   */
  async refresh(path?: string): Promise<void> {
    if (path !== undefined) {
      await this.loadDir(path)
    } else {
      // Refresh all expanded dirs
      const dirs = [...this.expandedDirs]
      await Promise.all(dirs.map((d) => this.loadDir(d)))
      // Also refresh root
      await this.loadDir(this.rootPath)
    }
  }

  /**
   * Expand all directories up to the given path.
   * Useful for revealing a file in the tree.
   */
  async revealPath(filePath: string): Promise<void> {
    const parts = filePath.split('/')
    let current = ''
    for (let i = 0; i < parts.length - 1; i++) {
      current = current ? `${current}/${parts[i]}` : parts[i]
      if (!this.expandedDirs.has(current)) {
        this.expandedDirs = new Set([...this.expandedDirs, current])
        if (!this.entries.has(current)) {
          await this.loadDir(current)
        }
      }
    }
    this.selectedFile = filePath
  }

  /**
   * Toggle sidebar visibility.
   */
  toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed
    void backendClient.uiUpdateLayout({ sidebarCollapsed: this.sidebarCollapsed })
  }

  /**
   * Get children for a given directory path.
   */
  getChildren(path: string): FileEntry[] {
    return this.entries.get(path) ?? []
  }

  /**
   * Check if a directory is expanded.
   */
  isExpanded(path: string): boolean {
    return this.expandedDirs.has(path)
  }

  /**
   * Check if a directory is currently loading.
   */
  isLoading(path: string): boolean {
    return this.loading.has(path)
  }

  /**
   * Begin inline creation of a new file or folder inside parentPath.
   */
  startCreation(parentPath: string, isDir: boolean): void {
    // Expand the parent so the inline input is visible
    if (!this.expandedDirs.has(parentPath)) {
      this.expandedDirs = new Set([...this.expandedDirs, parentPath])
      if (!this.entries.has(parentPath)) {
        this.loadDir(parentPath)
      }
    }
    this.pendingCreation = { parentPath, isDir }
  }

  cancelCreation(): void {
    this.pendingCreation = null
  }

  /**
   * Commit the new file or folder creation.
   */
  async commitCreation(name: string): Promise<void> {
    if (!this.pendingCreation || !name.trim()) {
      this.pendingCreation = null
      return
    }
    const { parentPath, isDir } = this.pendingCreation
    const fullPath = parentPath ? `${parentPath}/${name}` : name
    try {
      if (isDir) {
        await backendClient.createDir(fullPath)
      } else {
        await backendClient.writeFile(fullPath, '')
      }
      // Refresh the parent directory to show the new entry
      await this.loadDir(parentPath)
    } catch (err) {
      console.error('[file-tree] Failed to create:', err)
    } finally {
      this.pendingCreation = null
    }
  }
}

export const fileTree: FileTreeStore = import.meta.hot?.data?.fileTree ?? new FileTreeStore()
if (import.meta.hot) {
  import.meta.hot.data.fileTree = fileTree
}
