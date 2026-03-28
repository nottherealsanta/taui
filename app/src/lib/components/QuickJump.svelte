<!--
  QuickJump.svelte
  Cmd+P modal: fuzzy finder that searches both spec nodes and workspace files.
  - Spec nodes: instant (in-memory), icon: tree
  - Files: async search via backend fs/listDir, icon: file
-->
<script lang="ts">
  import { tick } from 'svelte'
  import { appState } from '$stores/app-state.svelte'
  import { fileTree } from '$stores/file-tree.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { dispatch } from '$stores/actions'
  import { backendClient } from '$services/backend-client'

  interface Props {
    onclose: () => void
  }
  const { onclose }: Props = $props()

  let query = $state('')
  let selectedIndex = $state(0)
  let inputEl: HTMLInputElement | undefined = $state()

  // ── Spec node results (instant, in-memory) ─────────────────────────────

  interface JumpItem {
    kind: 'spec' | 'file'
    label: string
    detail: string  // spec_ref or file path
    nodeId?: number
    filePath?: string
  }

  const specItems: JumpItem[] = $derived(
    appState.nodes
      .map((n, id) => ({
        kind: 'spec' as const,
        label: n.markdown.split('\n')[0].trim() || '...',
        detail: n.specRef,
        nodeId: id,
      }))
      .filter((n) => n.detail)
  )

  // ── File results (from cached file tree + async search) ─────────────────

  let fileSearchResults: JumpItem[] = $state([])
  let searching = $state(false)
  let searchTimer: ReturnType<typeof setTimeout> | null = null

  /**
   * Collect all known files from the file tree cache (already-loaded dirs).
   */
  function getCachedFiles(): JumpItem[] {
    const results: JumpItem[] = []
    for (const [_dir, entries] of fileTree.entries) {
      for (const entry of entries) {
        if (!entry.isDir) {
          results.push({
            kind: 'file',
            label: entry.name,
            detail: entry.path,
            filePath: entry.path,
          })
        }
      }
    }
    return results
  }

  // Debounced file search via backend when query changes
  $effect(() => {
    const q = query.trim()
    if (searchTimer) clearTimeout(searchTimer)

    if (q.length === 0) {
      fileSearchResults = getCachedFiles()
      return
    }

    // Start with cached files filtered locally
    const cached = getCachedFiles().filter((f) => {
      const lower = q.toLowerCase()
      return f.label.toLowerCase().includes(lower) || f.detail.toLowerCase().includes(lower)
    })
    fileSearchResults = cached

    // Also do an async backend search for deeper results
    searchTimer = setTimeout(async () => {
      searching = true
      try {
        const result = await backendClient.searchFiles(q, { caseSensitive: false })
        // Deduplicate by file path — add files from search results that aren't in cached
        const existing = new Set(cached.map((f) => f.filePath))
        const extra: JumpItem[] = []
        const seenPaths = new Set<string>()
        for (const sr of result.results) {
          if (!existing.has(sr.filePath) && !seenPaths.has(sr.filePath)) {
            seenPaths.add(sr.filePath)
            const name = sr.filePath.split('/').pop() ?? sr.filePath
            extra.push({
              kind: 'file',
              label: name,
              detail: sr.filePath,
              filePath: sr.filePath,
            })
          }
        }
        fileSearchResults = [...cached, ...extra]
      } catch {
        // Keep cached results on error
      } finally {
        searching = false
      }
    }, 200)
  })

  // ── Combined + filtered results ─────────────────────────────────────────

  const filtered: JumpItem[] = $derived.by(() => {
    const q = query.trim().toLowerCase()

    // Filter spec items
    const matchingSpecs = q === ''
      ? specItems.slice(0, 20)
      : specItems.filter((n) =>
          n.label.toLowerCase().includes(q) || n.detail.toLowerCase().includes(q)
        ).slice(0, 20)

    // File results are already filtered by the effect above
    const matchingFiles = fileSearchResults.slice(0, 30)

    // Interleave: files first (more common in Obsidian-like usage), then specs
    return [...matchingFiles, ...matchingSpecs].slice(0, 50)
  })

  // Reset selection when results change
  $effect(() => {
    void filtered.length
    selectedIndex = 0
  })

  $effect(() => {
    tick().then(() => inputEl?.focus())
  })

  // ── Actions ─────────────────────────────────────────────────────────────

  function select(item: JumpItem) {
    if (item.kind === 'spec' && item.nodeId !== undefined) {
      dispatch({ type: 'selectNode', nodeId: item.nodeId })
    } else if (item.kind === 'file' && item.filePath) {
      tabStore.openFile(item.filePath)
    }
    onclose()
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault(); onclose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault(); selectedIndex = Math.min(selectedIndex + 1, filtered.length - 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); selectedIndex = Math.max(selectedIndex - 1, 0)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = filtered[selectedIndex]
      if (item) select(item)
    }
  }

  function highlight(text: string, q: string): string {
    if (!q) return text
    const idx = text.toLowerCase().indexOf(q.toLowerCase())
    if (idx === -1) return text
    return (
      text.slice(0, idx) +
      '<mark>' +
      text.slice(idx, idx + q.length) +
      '</mark>' +
      text.slice(idx + q.length)
    )
  }

  function kindIcon(kind: 'spec' | 'file'): string {
    return kind === 'spec' ? '🌿' : '📄'
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="jump-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="jump-modal"
    role="dialog"
    aria-label="Quick jump"
    onclick={(e) => e.stopPropagation()}
    onkeydown={handleKeyDown}
  >
    <div class="jump-search">
      <span class="search-icon">⌘P</span>
      <input
        bind:this={inputEl}
        bind:value={query}
        class="search-input"
        type="text"
        placeholder="Search files and spec nodes..."
        autocomplete="off"
        spellcheck="false"
        aria-label="Quick jump search"
      />
      {#if searching}
        <span class="search-spinner">...</span>
      {/if}
    </div>

    <ul class="jump-list" role="listbox">
      {#each filtered as item, i (`${item.kind}-${item.detail}`)}
        <!-- svelte-ignore a11y_interactive_supports_focus -->
        <li
          class="jump-item"
          class:active={i === selectedIndex}
          role="option"
          aria-selected={i === selectedIndex}
          onmouseenter={() => { selectedIndex = i }}
          onclick={() => select(item)}
        >
          <span class="item-icon">{kindIcon(item.kind)}</span>
          <span class="item-label">{@html highlight(item.label, query)}</span>
          <span class="item-detail">{@html highlight(item.detail, query)}</span>
        </li>
      {/each}
      {#if filtered.length === 0}
        <li class="jump-empty">{query ? 'No matches found' : 'No files or nodes'}</li>
      {/if}
    </ul>

    <div class="jump-footer">
      <span>↑↓ navigate</span>
      <span>↵ open</span>
      <span>Esc close</span>
    </div>
  </div>
</div>

<style lang="postcss">
  .jump-backdrop {
    position: fixed;
    inset: 0;
    z-index: 500;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 80px;
  }

  .jump-modal {
    width: 560px;
    max-width: calc(100vw - 32px);
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    max-height: 450px;
  }

  .jump-search {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .search-icon {
    color: var(--fg-muted);
    font-size: 11px;
    font-family: var(--font-mono);
    flex-shrink: 0;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
    white-space: nowrap;
  }

  .search-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--fg-primary);
    font-size: 14px;
    caret-color: var(--fg-accent);
  }
  .search-input::placeholder { color: var(--fg-muted); }

  .search-spinner {
    color: var(--fg-muted);
    font-size: 12px;
    flex-shrink: 0;
    animation: pulse 1s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
  }

  .jump-list {
    list-style: none;
    margin: 0;
    padding: 4px 0;
    overflow-y: auto;
    flex: 1;
  }

  .jump-item {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 6px 14px;
    cursor: pointer;
    transition: background-color 0.1s;
  }
  .jump-item.active { background-color: var(--element-selected); }
  .jump-item:hover { background-color: var(--element-hover); }

  .item-icon {
    font-size: 12px;
    flex-shrink: 0;
    width: 18px;
    text-align: center;
  }

  .item-label {
    font-size: 13px;
    color: var(--fg-primary);
    flex-shrink: 0;
    max-width: 45%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .item-detail {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }

  :global(mark) {
    background: color-mix(in srgb, var(--fg-accent) 30%, transparent);
    color: inherit;
    border-radius: 2px;
  }

  .jump-empty {
    padding: 12px 14px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
    list-style: none;
  }

  .jump-footer {
    display: flex;
    gap: 16px;
    padding: 6px 14px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    font-size: 10px;
    color: var(--fg-muted);
  }
</style>
