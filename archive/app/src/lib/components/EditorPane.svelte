<!--
  EditorPane.svelte — Center editor container.

  Houses the TabBar and active tab's content (MarkdownEditor).
  Shows an empty state when no tabs are open.
-->
<script lang="ts">
  import TabBar from '$components/TabBar.svelte'
  import MarkdownEditor from '$components/MarkdownEditor.svelte'
  import FrontmatterProperties from '$components/FrontmatterProperties.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { stripFrontmatter } from '$lib/utils/specs'

  const activeTab = $derived(tabStore.activeTab)
  const editorContent = $derived(activeTab ? stripFrontmatter(activeTab.content) : '')
</script>

<div class="editor-pane">
  <TabBar />

  <div class="editor-area">
    {#if activeTab}
      <!-- Frontmatter display -->
      {#if activeTab.frontmatter && Object.keys(activeTab.frontmatter).length > 0}
        <FrontmatterProperties
          frontmatter={activeTab.frontmatter}
          tabId={activeTab.id}
        />
      {/if}

      <!-- File editor -->
      <MarkdownEditor
        content={editorContent}
        filePath={activeTab.filePath}
        tabId={activeTab.id}
      />
    {:else}
      <!-- Empty state -->
      <div class="empty-state">
        <div class="empty-icon">📝</div>
        <p class="empty-title">No file open</p>
        <p class="empty-hint">Open a file from the sidebar or use <kbd>Cmd+P</kbd> to quick jump</p>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .editor-pane {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    background-color: var(--bg-surface);
  }

  .editor-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--fg-muted);
    padding: 40px;
    text-align: center;
  }

  .empty-icon {
    font-size: 40px;
    line-height: 1;
    margin-bottom: 4px;
    opacity: 0.5;
  }

  .empty-title {
    margin: 0;
    font-size: 15px;
    color: var(--fg-primary);
  }

  .empty-hint {
    margin: 0;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .empty-hint kbd {
    font-family: var(--font-mono);
    font-size: 11px;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
  }
</style>
