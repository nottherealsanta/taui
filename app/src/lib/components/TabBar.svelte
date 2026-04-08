<!--
  TabBar.svelte — Horizontal tab bar at top of center pane.

  Shows open file tabs with: file name, dirty indicator, close button.
  Supports middle-click to close and tab selection.
-->
<script lang="ts">
  import { tabStore } from '$stores/tabs.svelte'

  const tabs = $derived(tabStore.tabs)
  const activeTabId = $derived(tabStore.activeTabId)

  function handleTabClick(tabId: string) {
    void tabStore.setActiveTab(tabId)
  }

  function handleTabKeyDown(e: KeyboardEvent, tabId: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      void tabStore.setActiveTab(tabId)
    }
  }

  function handleCloseTab(e: MouseEvent, tabId: string) {
    e.stopPropagation()
    void tabStore.closeTab(tabId)
  }

  function handleMiddleClick(e: MouseEvent, tabId: string) {
    if (e.button === 1) {
      e.preventDefault()
      void tabStore.closeTab(tabId)
    }
  }

  function handleContextMenu(e: MouseEvent, _tabId: string) {
    e.preventDefault()
    // Simple context menu: close / close others / close all
    // For now, just close the tab on right-click
  }
</script>

{#if tabs.length > 0}
  <div class="tab-bar" role="tablist">
    {#each tabs as tab (tab.id)}
      <!-- svelte-ignore a11y_interactive_supports_focus -->
      <div
        class="tab"
        class:active={tab.id === activeTabId}
        class:dirty={tab.isDirty}
        role="tab"
        tabindex="0"
        aria-selected={tab.id === activeTabId}
        onclick={() => handleTabClick(tab.id)}
        onkeydown={(e) => handleTabKeyDown(e, tab.id)}
        onauxclick={(e) => handleMiddleClick(e, tab.id)}
        oncontextmenu={(e) => handleContextMenu(e, tab.id)}
      >
        <span class="tab-label">{tab.title}</span>
        {#if tab.isDirty}
          <span class="dirty-indicator" aria-label="Unsaved changes"></span>
        {/if}
        <button
          class="close-btn"
          onclick={(e) => handleCloseTab(e, tab.id)}
          aria-label="Close tab"
        >✕</button>
      </div>
    {/each}
  </div>
{/if}

<style lang="postcss">
  .tab-bar {
    display: flex;
    align-items: stretch;
    background-color: var(--bg-base);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    overflow-x: auto;
    overflow-y: hidden;
    min-height: 33px;
  }

  /* Hide scrollbar */
  .tab-bar::-webkit-scrollbar {
    height: 0;
  }

  .tab {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 0 8px;
    min-width: 0;
    max-width: 180px;
    cursor: pointer;
    font-size: 12px;
    color: var(--fg-muted);
    border-right: 1px solid var(--border-variant);
    transition: all 0.1s;
    flex-shrink: 0;
    height: 33px;
  }

  .tab:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .tab.active {
    background-color: var(--bg-surface);
    color: var(--fg-primary);
    border-bottom: 2px solid var(--fg-accent);
  }

  .tab-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dirty-indicator {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--fg-accent);
    flex-shrink: 0;
  }

  .close-btn {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 10px;
    padding: 2px;
    border-radius: 2px;
    line-height: 1;
    flex-shrink: 0;
    opacity: 0;
    transition: all 0.1s;
  }

  .tab:hover .close-btn {
    opacity: 1;
  }

  .close-btn:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .tab.dirty .close-btn {
    opacity: 0;
  }

  .tab.dirty:hover .close-btn {
    opacity: 1;
  }

  .tab.dirty:hover .dirty-indicator {
    display: none;
  }
</style>
