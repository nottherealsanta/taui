<script lang="ts">
  import MonacoEditor from '$components/MonacoEditor.svelte'

  interface Props {
    filePath: string
    target?: string | null
    /** The resolved snippet content (function/variable/line range) */
    snippetContent?: string | null
    /** The full file content */
    fullFileContent?: string | null
    language?: string | null
    lineStart?: number | null
    lineEnd?: number | null
    loading?: boolean
    error?: string | null
    emptyMessage?: string | null
    onclose: () => void
  }

  const {
    filePath,
    target = null,
    snippetContent = null,
    fullFileContent = null,
    language = null,
    lineStart = null,
    lineEnd = null,
    loading = false,
    error = null,
    emptyMessage = null,
    onclose,
  }: Props = $props()

  let showFullFile = $state(false)

  // Determine what content to display - treat empty strings as falsy
  const hasSnippet = $derived(Boolean(snippetContent && snippetContent.trim().length > 0))
  const hasFullFile = $derived(Boolean(fullFileContent && fullFileContent.trim().length > 0))
  const canToggle = $derived(hasSnippet && hasFullFile)
  
  const displayContent = $derived(
    showFullFile
      ? (hasFullFile ? fullFileContent! : (hasSnippet ? snippetContent! : ''))
      : (hasSnippet ? snippetContent! : (hasFullFile ? fullFileContent! : ''))
  )

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      onclose()
    }
  }

  function toggleView(): void {
    showFullFile = !showFullFile
  }
</script>

<svelte:window onkeydown={handleKeyDown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="code-file-modal-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div class="code-file-modal" role="dialog" aria-label="Code reference file" onclick={(event) => event.stopPropagation()}>
    <div class="code-file-modal__header">
      <div class="code-file-modal__meta">
        <div class="code-file-modal__title">{filePath}</div>
        <div class="code-file-modal__subtitle">
          {#if target}
            <span>{target}</span>
          {/if}
          {#if hasSnippet && lineStart !== null && !showFullFile}
            <span>
              Lines {lineStart}{#if lineEnd !== null && lineEnd !== lineStart}–{lineEnd}{/if}
            </span>
          {/if}
          {#if showFullFile || !hasSnippet}
            <span>Full file</span>
          {/if}
        </div>
      </div>
      <div class="code-file-modal__actions">
        {#if canToggle}
          <button class="code-file-modal__toggle" onclick={toggleView}>
            {showFullFile ? 'Show snippet' : 'Show full file'}
          </button>
        {/if}
        <button class="code-file-modal__close" onclick={onclose} aria-label="Close code file modal">✕</button>
      </div>
    </div>

    <div class="code-file-modal__body">
      {#if loading}
        <div class="code-file-modal__empty">Loading…</div>
      {:else if emptyMessage}
        <div class="code-file-modal__empty">{emptyMessage}</div>
      {:else if error}
        <div class="code-file-modal__empty code-file-modal__empty--error">{error}</div>
      {:else}
        <MonacoEditor value={displayContent} language={language ?? 'plaintext'} readOnly={true} />
      {/if}
    </div>
  </div>
</div>

<style lang="postcss">
  .code-file-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 650;
    background-color: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 28px;
  }

  .code-file-modal {
    width: min(1120px, calc(100vw - 56px));
    height: min(78vh, 860px);
    display: flex;
    flex-direction: column;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    overflow: hidden;
  }

  .code-file-modal__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 18px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
  }

  .code-file-modal__meta {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .code-file-modal__title {
    font-size: 13px;
    line-height: 1.4;
    color: var(--fg-primary);
    font-family: var(--font-mono);
    word-break: break-all;
  }

  .code-file-modal__subtitle {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 11px;
    color: var(--fg-muted);
  }

  .code-file-modal__subtitle span {
    padding: 2px 7px;
    border: 1px solid var(--border);
    background: transparent;
  }

  .code-file-modal__actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .code-file-modal__toggle {
    padding: 6px 12px;
    font-size: 12px;
    color: var(--fg-secondary);
    background: transparent;
    border: 1px solid var(--border);
    cursor: pointer;
    transition: background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease;
  }

  .code-file-modal__toggle:hover {
    color: var(--fg-primary);
    background: var(--bg-surface);
  }

  .code-file-modal__close {
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid transparent;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    transition: background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease;
  }

  .code-file-modal__close:hover {
    color: var(--fg-primary);
    border-color: var(--border);
    background: var(--bg-surface);
  }

  .code-file-modal__body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .code-file-modal__empty {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    color: var(--fg-muted);
    font-size: 13px;
  }

  .code-file-modal__empty--error {
    color: var(--status-error);
  }
</style>
