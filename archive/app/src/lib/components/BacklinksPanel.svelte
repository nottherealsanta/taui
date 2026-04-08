<!--
  BacklinksPanel.svelte — Shows files that link to the current file.

  Fetches backlinks from the backend and displays them with context snippets.
  Click to open the linking file.
-->
<script lang="ts">
  import { tabStore } from '$stores/tabs.svelte'
  import { backendClient } from '$services/backend-client'

  const activeTab = $derived(tabStore.activeTab)

  let backlinks: Array<{ filePath: string; lineNumber: number; context: string }> = $state([])
  let loading = $state(false)
  let lastFilePath: string | null = $state(null)

  // Reload backlinks when active file changes
  $effect(() => {
    const filePath = activeTab?.filePath ?? null
    if (filePath !== lastFilePath) {
      lastFilePath = filePath
      if (filePath) {
        loadBacklinks(filePath)
      } else {
        backlinks = []
      }
    }
  })

  async function loadBacklinks(filePath: string) {
    loading = true
    try {
      const result = await backendClient.getBacklinks(filePath)
      backlinks = result.backlinks
    } catch (err) {
      console.error('[backlinks] Failed to load', err)
      backlinks = []
    } finally {
      loading = false
    }
  }

  function handleClick(filePath: string) {
    tabStore.openFile(filePath)
  }
</script>

<div class="backlinks-panel">
  {#if !activeTab}
    <div class="empty">No file open</div>
  {:else if loading}
    <div class="empty">Loading backlinks…</div>
  {:else if backlinks.length === 0}
    <div class="empty">No backlinks found</div>
  {:else}
    <div class="backlink-count">{backlinks.length} backlink{backlinks.length !== 1 ? 's' : ''}</div>
    <ul class="backlink-list">
      {#each backlinks as link (link.filePath + ':' + link.lineNumber)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <li class="backlink-item" onclick={() => handleClick(link.filePath)}>
          <div class="backlink-file">
            <span class="file-icon">📄</span>
            <span class="file-path">{link.filePath}</span>
            <span class="line-num">:{link.lineNumber}</span>
          </div>
          <div class="backlink-context">{link.context}</div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style lang="postcss">
  .backlinks-panel {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }

  .empty {
    padding: 16px 12px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
  }

  .backlink-count {
    padding: 4px 12px;
    font-size: 11px;
    color: var(--fg-muted);
  }

  .backlink-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .backlink-item {
    padding: 6px 12px;
    cursor: pointer;
    transition: background-color 0.1s;
    border-bottom: 1px solid var(--border-variant);
  }

  .backlink-item:hover {
    background-color: var(--element-hover);
  }

  .backlink-file {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    margin-bottom: 2px;
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

  .line-num {
    color: var(--fg-muted);
    font-family: var(--font-mono);
    font-size: 10px;
    flex-shrink: 0;
  }

  .backlink-context {
    font-size: 11px;
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding-left: 18px;
  }
</style>
