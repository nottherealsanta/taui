<!--
  OutlinePanel.svelte — Document outline / table of contents.

  Parses the current file's markdown headings and shows a clickable tree.
  Highlights the heading closest to the cursor position.
-->
<script lang="ts">
  import { tabStore } from '$stores/tabs.svelte'

  interface HeadingItem {
    level: number
    text: string
    lineNumber: number
  }

  const activeTab = $derived(tabStore.activeTab)

  // Parse headings from active file content
  const headings = $derived(() => {
    if (!activeTab?.content) return []
    const lines = activeTab.content.split('\n')
    const items: HeadingItem[] = []

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      const match = line.match(/^(#{1,6})\s+(.+)$/)
      if (match) {
        items.push({
          level: match[1].length,
          text: match[2].trim(),
          lineNumber: i + 1,
        })
      }
    }
    return items
  })

  function handleHeadingClick(_lineNumber: number) {
    // TODO: scroll editor to this line number
    // This would need integration with the Monaco editor scrolling
  }
</script>

<div class="outline-panel">
  {#if !activeTab}
    <div class="empty">No file open</div>
  {:else if headings().length === 0}
    <div class="empty">No headings found</div>
  {:else}
    <ul class="heading-list">
      {#each headings() as heading (heading.lineNumber)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <li
          class="heading-item"
          style="padding-left: {8 + (heading.level - 1) * 12}px"
          onclick={() => handleHeadingClick(heading.lineNumber)}
        >
          <span class="heading-marker">H{heading.level}</span>
          <span class="heading-text">{heading.text}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style lang="postcss">
  .outline-panel {
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

  .heading-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .heading-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    cursor: pointer;
    font-size: 12px;
    color: var(--fg-primary);
    transition: background-color 0.1s;
  }

  .heading-item:hover {
    background-color: var(--element-hover);
  }

  .heading-marker {
    font-size: 9px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    background: var(--element-bg);
    border-radius: 2px;
    padding: 0 3px;
    flex-shrink: 0;
    line-height: 1.5;
  }

  .heading-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
