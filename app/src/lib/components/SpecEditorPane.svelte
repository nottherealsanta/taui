<script lang="ts">
  import TabBar from '$components/TabBar.svelte'
  import LiveMarkdownEditor from '$components/LiveMarkdownEditor.svelte'
  import FrontmatterProperties from '$components/FrontmatterProperties.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { stripFrontmatter } from '$lib/utils/specs'

  const activeTab = $derived(tabStore.activeTab)
  const editorContent = $derived(activeTab ? stripFrontmatter(activeTab.content) : '')
</script>

<section class="spec-editor-pane">
  <TabBar />

  <div class="editor-area">
    {#if activeTab}
      {#if activeTab.frontmatter && Object.keys(activeTab.frontmatter).length > 0}
        <FrontmatterProperties
          frontmatter={activeTab.frontmatter}
          tabId={activeTab.id}
        />
      {/if}
      {#key activeTab.id}
        <LiveMarkdownEditor
          content={editorContent}
          filePath={activeTab.filePath}
          tabId={activeTab.id}
        />
      {/key}
    {:else}
      <div class="empty-state">
        <p class="empty-title">Select a spec from the sidebar</p>
        <p class="empty-hint">Open multiple specs as tabs on the left while keeping agent work visible on the right.</p>
      </div>
    {/if}
  </div>
</section>

<style lang="postcss">
  .spec-editor-pane {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    background-color: var(--bg-surface);
  }

  .editor-area {
    display: flex;
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 32px;
    color: var(--fg-muted);
  }

  .empty-title {
    margin: 0 0 8px;
    font-size: 15px;
    color: var(--fg-primary);
  }

  .empty-hint {
    margin: 0;
    max-width: 34ch;
    line-height: 1.5;
  }
</style>