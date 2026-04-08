<!--
  SearchPanel.svelte — Full-text search UI.

  Features:
  - Search input with regex, case-sensitive, file filter options
  - Results grouped by file
  - Click to open file at matching line
  - Toggle via Cmd+Shift+F or sidebar icon
-->
<script lang="ts">
  import type { SearchResult } from '$types/index'
  import { backendClient } from '$services/backend-client'
  import { tabStore } from '$stores/tabs.svelte'

  interface Props {
    onclose?: () => void
  }
  const { onclose }: Props = $props()

  let query = $state('')
  let regex = $state(false)
  let caseSensitive = $state(false)
  let filePattern = $state('*.md')
  let results: SearchResult[] = $state([])
  let loading = $state(false)
  let searched = $state(false)
  let searchTimer: ReturnType<typeof setTimeout> | null = null

  // Debounced search
  function handleInput() {
    if (searchTimer) clearTimeout(searchTimer)
    if (!query.trim()) {
      results = []
      searched = false
      return
    }
    searchTimer = setTimeout(() => {
      doSearch()
    }, 300)
  }

  async function doSearch() {
    if (!query.trim()) return
    loading = true
    searched = true
    try {
      const response = await backendClient.searchFiles(query, {
        regex,
        caseSensitive,
        filePattern: filePattern || undefined,
      })
      results = response.results
    } catch (err) {
      console.error('[search] Failed', err)
      results = []
    } finally {
      loading = false
    }
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      doSearch()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onclose?.()
    }
  }

  function openResult(result: SearchResult) {
    tabStore.openFile(result.filePath)
  }

  // Group results by file
  const groupedResults = $derived(() => {
    const groups = new Map<string, SearchResult[]>()
    for (const r of results) {
      const existing = groups.get(r.filePath) ?? []
      existing.push(r)
      groups.set(r.filePath, existing)
    }
    return [...groups.entries()]
  })
</script>

<div class="search-panel">
  <div class="search-header">
    <input
      class="search-input"
      type="text"
      placeholder="Search in files…"
      bind:value={query}
      oninput={handleInput}
      onkeydown={handleKeyDown}
      autocomplete="off"
      spellcheck="false"
    />
    <div class="search-options">
      <label class="option">
        <input type="checkbox" bind:checked={regex} onchange={doSearch} />
        <span>Regex</span>
      </label>
      <label class="option">
        <input type="checkbox" bind:checked={caseSensitive} onchange={doSearch} />
        <span>Aa</span>
      </label>
      <input
        class="file-filter"
        type="text"
        placeholder="File filter"
        bind:value={filePattern}
        onchange={doSearch}
      />
    </div>
  </div>

  <div class="search-results">
    {#if loading}
      <div class="status">Searching…</div>
    {:else if !searched}
      <div class="status">Type to search</div>
    {:else if results.length === 0}
      <div class="status">No results found</div>
    {:else}
      <div class="result-count">{results.length} result{results.length !== 1 ? 's' : ''}</div>
      {#each groupedResults() as [filePath, fileResults] (filePath)}
        <div class="result-group">
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="group-header" onclick={() => openResult(fileResults[0])}>
            <span class="file-icon">📄</span>
            <span class="file-path">{filePath}</span>
            <span class="match-count">{fileResults.length}</span>
          </div>
          {#each fileResults as result (result.lineNumber)}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="result-line" onclick={() => openResult(result)}>
              <span class="line-num">{result.lineNumber}</span>
              <span class="line-content">{result.lineContent}</span>
            </div>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style lang="postcss">
  .search-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .search-header {
    padding: 8px;
    border-bottom: 1px solid var(--border-variant);
    flex-shrink: 0;
  }

  .search-input {
    width: 100%;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--fg-primary);
    font-size: 12px;
    padding: 6px 8px;
    outline: none;
    margin-bottom: 6px;
  }

  .search-input:focus {
    border-color: var(--fg-accent);
  }

  .search-input::placeholder {
    color: var(--fg-muted);
  }

  .search-options {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .option {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: 11px;
    color: var(--fg-muted);
    cursor: pointer;
  }

  .option input[type="checkbox"] {
    width: 12px;
    height: 12px;
    accent-color: var(--fg-accent);
  }

  .file-filter {
    flex: 1;
    min-width: 60px;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--fg-primary);
    font-size: 10px;
    font-family: var(--font-mono);
    padding: 2px 6px;
    outline: none;
  }

  .file-filter:focus {
    border-color: var(--fg-accent);
  }

  .search-results {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }

  .status {
    padding: 16px 12px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
  }

  .result-count {
    padding: 4px 12px;
    font-size: 10px;
    color: var(--fg-muted);
  }

  .result-group {
    margin-bottom: 4px;
  }

  .group-header {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    font-size: 12px;
    cursor: pointer;
    transition: background-color 0.1s;
  }

  .group-header:hover {
    background-color: var(--element-hover);
  }

  .file-icon {
    font-size: 10px;
    flex-shrink: 0;
  }

  .file-path {
    color: var(--fg-accent);
    font-family: var(--font-mono);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .match-count {
    margin-left: auto;
    font-size: 10px;
    color: var(--fg-muted);
    background: var(--element-bg);
    border-radius: 8px;
    padding: 0 5px;
    flex-shrink: 0;
  }

  .result-line {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 2px 8px 2px 24px;
    font-size: 11px;
    cursor: pointer;
    transition: background-color 0.1s;
  }

  .result-line:hover {
    background-color: var(--element-hover);
  }

  .line-num {
    color: var(--fg-muted);
    font-family: var(--font-mono);
    font-size: 10px;
    flex-shrink: 0;
    min-width: 30px;
    text-align: right;
  }

  .line-content {
    color: var(--fg-primary);
    font-family: var(--font-mono);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
