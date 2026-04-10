<!--
  EmbeddedCodeBlock.svelte
  Renders a ::code directive as an embedded, editable code window.
  
  The code is fetched from the backend via code/resolve and edits
  are written back via code/update.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { backendClient } from '$services/backend-client'
  import { theme as themeStore } from '$stores/theme.svelte'
  import { registerMonacoThemes, monacoThemeName } from '$services/monaco-theme'
  import type * as Monaco from 'monaco-editor'

  interface Props {
    filePath: string
    target: string
    refKind: 'symbol' | 'lines'
    onHeightChange?: (height: number) => void
  }

  const { filePath, target, refKind, onHeightChange }: Props = $props()

  let container: HTMLElement | undefined = $state()
  let editor: Monaco.editor.IStandaloneCodeEditor | null = null
  let monaco: typeof Monaco | null = null
  let resizeObs: ResizeObserver | null = null

  // Resolved data
  let content: string | null = $state(null)
  let language: string | null = $state(null)
  let resolvedStart: number | null = $state(null)
  let resolvedEnd: number | null = $state(null)
  let diagnostic: string = $state('pending')
  let error: string | null = $state(null)
  let loading: boolean = $state(true)
  let saving: boolean = $state(false)
  let dirty: boolean = $state(false)
  let collapsed: boolean = $state(false)

  const activeTheme = $derived(monacoThemeName(themeStore.isDark))

  // Debounce timer for saving
  let saveTimeout: ReturnType<typeof setTimeout> | null = null

  async function resolveCode() {
    loading = true
    error = null
    try {
      const result = await backendClient.codeResolve(filePath, target, refKind)
      content = result.content
      language = result.language
      resolvedStart = result.resolvedStart
      resolvedEnd = result.resolvedEnd
      diagnostic = result.diagnostic
      if (result.error) {
        error = result.error
      }
    } catch (e) {
      error = String(e)
      diagnostic = 'unresolved'
    } finally {
      loading = false
    }
  }

  async function saveCode(newContent: string) {
    if (resolvedStart === null || resolvedEnd === null) return
    
    saving = true
    try {
      const result = await backendClient.codeUpdate(
        filePath,
        resolvedStart,
        resolvedEnd,
        newContent
      )
      if (result.success) {
        // Update line range in case it changed
        if (result.lineStart !== undefined) resolvedStart = result.lineStart
        if (result.lineEnd !== undefined) resolvedEnd = result.lineEnd
        dirty = false
        diagnostic = 'resolved'
      } else {
        error = result.error || 'Failed to save'
      }
    } catch (e) {
      error = String(e)
    } finally {
      saving = false
    }
  }

  function handleContentChange(newContent: string) {
    dirty = true
    // Debounce save
    if (saveTimeout) clearTimeout(saveTimeout)
    saveTimeout = setTimeout(() => {
      void saveCode(newContent)
    }, 1000)
  }

  function toggleCollapsed() {
    collapsed = !collapsed
    if (onHeightChange) {
      // Notify parent of height change for widget resize
      requestAnimationFrame(() => {
        if (container) {
          onHeightChange(container.offsetHeight)
        }
      })
    }
  }

  onMount(async () => {
    void resolveCode()
  })

  // Initialize Monaco when content is ready
  $effect(() => {
    if (content === null || !container || collapsed) return
    if (editor) return // Already initialized

    void (async () => {
      monaco = await import('monaco-editor')
      registerMonacoThemes(monaco)

      const lineCount = content!.split('\n').length
      const editorHeight = Math.min(Math.max(lineCount * 18 + 16, 60), 400)

      editor = monaco.editor.create(container!, {
        value: content!,
        language: language || 'plaintext',
        readOnly: false,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        folding: true,
        renderLineHighlight: 'line',
        automaticLayout: false,
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 12,
        lineHeight: 18,
        padding: { top: 8, bottom: 8 },
        theme: activeTheme,
        lineNumbers: resolvedStart !== null
          ? (n: number) => String(n + (resolvedStart || 1) - 1)
          : 'on',
        scrollbar: {
          vertical: 'auto',
          horizontal: 'auto',
          verticalScrollbarSize: 8,
          horizontalScrollbarSize: 8,
        },
      })

      // Set initial height
      container!.style.height = `${editorHeight}px`
      editor.layout()

      // Notify parent of height
      if (onHeightChange) {
        onHeightChange(container!.offsetHeight + 32) // +32 for header
      }

      // Listen for content changes
      editor.onDidChangeModelContent(() => {
        const model = editor!.getModel()
        if (model) {
          handleContentChange(model.getValue())
        }
      })

      // ResizeObserver for responsive layout
      resizeObs = new ResizeObserver(() => editor?.layout())
      resizeObs.observe(container!)
    })()
  })

  // Update theme
  $effect(() => {
    if (!monaco) return
    monaco.editor.setTheme(activeTheme)
  })

  onDestroy(() => {
    if (saveTimeout) clearTimeout(saveTimeout)
    resizeObs?.disconnect()
    editor?.dispose()
    editor = null
  })
</script>

<div class="embedded-code-block" class:collapsed class:dirty class:error={diagnostic === 'unresolved'}>
  <div class="header" role="button" tabindex="0" onclick={toggleCollapsed} onkeydown={(e) => e.key === 'Enter' && toggleCollapsed()}>
    <span class="icon">{collapsed ? '▶' : '▼'}</span>
    <span class="file-path">{filePath}</span>
    <span class="target">:{target}</span>
    {#if saving}
      <span class="status saving">saving...</span>
    {:else if dirty}
      <span class="status dirty">modified</span>
    {:else if diagnostic === 'unresolved'}
      <span class="status error">unresolved</span>
    {:else if diagnostic === 'stale'}
      <span class="status stale">stale</span>
    {/if}
    {#if resolvedStart !== null && resolvedEnd !== null}
      <span class="lines">L{resolvedStart}-{resolvedEnd}</span>
    {/if}
  </div>
  
  {#if !collapsed}
    <div class="editor-container">
      {#if loading}
        <div class="loading">Loading...</div>
      {:else if error}
        <div class="error-message">{error}</div>
      {:else}
        <div class="monaco-wrapper" bind:this={container}></div>
      {/if}
    </div>
  {/if}
</div>

<style lang="postcss">
  .embedded-code-block {
    margin: 8px 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    background: var(--bg-surface);
  }

  .embedded-code-block.error {
    border-color: var(--status-error);
  }

  .embedded-code-block.dirty {
    border-color: var(--status-warning);
  }

  .header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: var(--element-bg);
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    cursor: pointer;
    user-select: none;
  }

  .header:hover {
    background: var(--element-bg-hover);
  }

  .icon {
    font-size: 9px;
    color: var(--fg-muted);
    width: 12px;
  }

  .file-path {
    color: var(--fg-accent);
    font-family: var(--font-mono);
  }

  .target {
    color: var(--fg-secondary);
    font-family: var(--font-mono);
  }

  .status {
    margin-left: auto;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 500;
  }

  .status.saving {
    background: var(--fg-accent);
    color: var(--bg-surface);
  }

  .status.dirty {
    background: var(--status-warning);
    color: var(--bg-surface);
  }

  .status.error {
    background: var(--status-error);
    color: white;
  }

  .status.stale {
    background: var(--fg-muted);
    color: var(--bg-surface);
  }

  .lines {
    color: var(--fg-muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }

  .editor-container {
    min-height: 60px;
  }

  .loading,
  .error-message {
    padding: 16px;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .error-message {
    color: var(--status-error);
  }

  .monaco-wrapper {
    height: 200px;
    min-height: 60px;
    max-height: 400px;
  }

  .collapsed .editor-container {
    display: none;
  }
</style>
