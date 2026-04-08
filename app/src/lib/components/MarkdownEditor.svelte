<!--
  MarkdownEditor.svelte — Rich markdown editing component.

  Uses Monaco for source mode editing.
  Provides a basic textarea fallback for live preview.
  Supports Cmd+S to save.
-->
<script lang="ts">
  import MonacoEditor from '$components/MonacoEditor.svelte'
  import { tabStore } from '$stores/tabs.svelte'

  interface Props {
    content: string
    filePath: string
    tabId: string
    readOnly?: boolean
  }
  const { content, filePath, tabId, readOnly = false }: Props = $props()

  let mode: 'source' | 'preview' = $state('source')

  // Detect language from file extension
  const language = $derived.by(() => {
    const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
    switch (ext) {
      case 'md': return 'markdown'
      case 'ts': case 'tsx': return 'typescript'
      case 'js': case 'jsx': return 'javascript'
      case 'py': return 'python'
      case 'json': return 'json'
      case 'css': return 'css'
      case 'html': return 'html'
      case 'yaml': case 'yml': return 'yaml'
      case 'toml': return 'toml'
      case 'svelte': return 'html'
      case 'rs': return 'rust'
      default: return 'plaintext'
    }
  })

  function handleSave() {
    tabStore.save(tabId)
  }

  function handleKeyDown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      handleSave()
    }
  }

  function handleMonacoChange(newContent: string) {
    tabStore.updateContent(tabId, newContent)
  }

  function handleContentChange(e: Event) {
    const target = e.target as HTMLTextAreaElement
    tabStore.updateContent(tabId, target.value)
  }
</script>

<div class="markdown-editor" onkeydown={handleKeyDown}>
  <!-- Mode toggle -->
  <div class="editor-toolbar">
    <div class="mode-toggle">
      <button
        class="mode-btn"
        class:active={mode === 'source'}
        onclick={() => { mode = 'source' }}
      >Source</button>
      <button
        class="mode-btn"
        class:active={mode === 'preview'}
        onclick={() => { mode = 'preview' }}
      >Preview</button>
    </div>
    <span class="file-path">{filePath}</span>
  </div>

  <!-- Editor content -->
  <div class="editor-content">
    {#if mode === 'source'}
      <MonacoEditor
        value={content}
        language={language}
        readOnly={readOnly}
        lineStart={1}
        onchange={handleMonacoChange}
      />
    {:else}
      <div class="preview-pane selectable">
        <textarea
          class="preview-textarea"
          value={content}
          oninput={handleContentChange}
          readonly={readOnly}
          spellcheck="false"
        ></textarea>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .markdown-editor {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .editor-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-variant);
    flex-shrink: 0;
    background-color: var(--bg-surface);
  }

  .mode-toggle {
    display: flex;
    gap: 2px;
    background-color: var(--element-bg);
    border-radius: 4px;
    padding: 2px;
  }

  .mode-btn {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 3px;
    transition: all 0.15s;
  }

  .mode-btn.active {
    background-color: var(--bg-elevated);
    color: var(--fg-primary);
  }

  .mode-btn:hover:not(.active) {
    color: var(--fg-primary);
  }

  .file-path {
    font-size: 10px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .editor-content {
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .preview-pane {
    flex: 1;
    overflow: auto;
    padding: 0;
  }

  .preview-textarea {
    width: 100%;
    height: 100%;
    background: var(--bg-surface);
    color: var(--fg-primary);
    border: none;
    outline: none;
    resize: none;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    padding: 16px 24px;
  }
</style>
