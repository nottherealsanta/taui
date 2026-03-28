<!--
  6.x BottomDrawer.svelte
  Collapsible bottom drawer with:
  - Code tab: Monaco, real line numbers, expand/collapse toggle, getNodeSourceRange
  - Terminal tab: command input, Run/Stop controls, streamed run/output via appState
-->
<script lang="ts">
  import { tick } from 'svelte'
  import MonacoEditor from './MonacoEditor.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  interface CodePreview {
    specRef?: string | null
    filePath: string
    content: string
    lineStart: number | null
    lineEnd: number | null
    language?: string
    /** Whether this preview came from getNodeSourceRange (may be truncated). */
    truncated?: boolean
    previewStart?: number | null
    previewEnd?: number | null
  }

  interface Props {
    codePreview?: CodePreview | null
    onclose?: () => void
  }
  let { codePreview = null, onclose }: Props = $props()

  type Tab = 'code' | 'terminal'
  let activeTab: Tab = $state('code')
  let height = $state(240)       // px
  let dragging = $state(false)
  let dragStartY = 0
  let dragStartH = 0

  // ── Code tab: expand/collapse ──────────────────────────────────────────────
  let codeExpanded = $state(false)
  let codeLoading = $state(false)
  // Local override of content after expand
  let expandedPreview: CodePreview | null = $state(null)

  const activePreview = $derived(expandedPreview ?? codePreview)

  async function toggleExpand() {
    if (!codePreview?.specRef) return
    if (codeExpanded) {
      // Collapse back to default preview
      codeExpanded = false
      expandedPreview = null
    } else {
      codeLoading = true
      try {
        const resp = await backendClient.getNodeSourceRange(codePreview.specRef, {
          expanded: true,
        })
        expandedPreview = {
          specRef: codePreview.specRef,
          filePath: resp.file_path,
          content: resp.content,
          lineStart: resp.line_start,
          lineEnd: resp.line_end,
          previewStart: resp.preview_start,
          previewEnd: resp.preview_end,
          language: codePreview.language,
          truncated: resp.truncated,
        }
        codeExpanded = true
      } catch (e) {
        console.error('[BottomDrawer] expand failed', e)
      } finally {
        codeLoading = false
      }
    }
  }

  // Reset expanded state when codePreview changes
  $effect(() => {
    if (codePreview) {
      codeExpanded = false
      expandedPreview = null
    }
  })

  // ── Terminal tab ───────────────────────────────────────────────────────────
  let commandInput = $state('')
  let runLoading = $state(false)
  let outputEl: HTMLElement | undefined = $state()

  const runState = $derived(appState.runState)
  const isRunning = $derived(runState.status === 'running')

  // Auto-scroll output when new lines come in
  $effect(() => {
    // Subscribe to lines length for reactivity
    void runState.lines.length
    if (outputEl) {
      tick().then(() => {
        if (outputEl) outputEl.scrollTop = outputEl.scrollHeight
      })
    }
  })

  async function handleRun() {
    const cmd = commandInput.trim()
    if (!cmd || isRunning) return
    const specRef = appState.selectedSpecRef ?? ''
    appState.clearRunOutput()
    appState.setRunStatus('running', null, specRef, cmd)
    runLoading = true
    try {
      const resp = await backendClient.runStart(specRef, cmd)
      // Backend response gives us the assigned run_id
      appState.setRunStatus(
        (resp.status as 'running' | 'idle') ?? 'running',
        resp.run_id ?? null,
        resp.spec_ref ?? specRef,
        cmd,
      )
    } catch (e) {
      appState.addRunLine({ stream: 'stderr', text: `Error: ${String(e)}` })
      appState.setRunStatus('error', null, specRef, cmd, -1)
    } finally {
      runLoading = false
    }
  }

  async function handleStop() {
    try {
      await backendClient.runStop()
    } catch (e) {
      console.error('[BottomDrawer] runStop failed', e)
    }
  }

  function handleCommandKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleRun()
    }
  }

  // ── Resize drag ────────────────────────────────────────────────────────────
  function onDragMouseDown(e: MouseEvent) {
    dragging = true
    dragStartY = e.clientY
    dragStartH = height
    e.preventDefault()
  }

  function onMouseMove(e: MouseEvent) {
    if (!dragging) return
    const delta = dragStartY - e.clientY
    height = Math.max(100, Math.min(800, dragStartH + delta))
  }

  function onMouseUp() { dragging = false }

  // Infer language from file extension
  function inferLanguage(filePath: string): string {
    const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
    const map: Record<string, string> = {
      rs: 'rust', ts: 'typescript', tsx: 'typescript', js: 'javascript',
      jsx: 'javascript', py: 'python', json: 'json', yaml: 'yaml', yml: 'yaml',
      md: 'markdown', html: 'html', css: 'css', toml: 'toml', sh: 'shell',
    }
    return map[ext] ?? 'plaintext'
  }

  function exitStatusLabel(code: number | null, status: string): string {
    if (status === 'stopped') return 'stopped'
    if (code === null) return status
    return code === 0 ? `exit 0` : `exit ${code}`
  }
</script>

<svelte:window onmousemove={onMouseMove} onmouseup={onMouseUp} />

<div
  class="bottom-drawer"
  style:height="{height}px"
>
  <!-- Drag handle -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="drag-handle"
    class:dragging
    onmousedown={onDragMouseDown}
  >
    <div class="drag-grip"></div>
  </div>

  <!-- Tab bar -->
  <div class="tab-bar">
    <button
      class="tab"
      class:active={activeTab === 'code'}
      onclick={() => { activeTab = 'code' }}
    >Code</button>
    <button
      class="tab"
      class:active={activeTab === 'terminal'}
      onclick={() => { activeTab = 'terminal' }}
    >
      Terminal
      {#if isRunning}
        <span class="run-dot" aria-label="running"></span>
      {/if}
    </button>

    <div class="tab-spacer"></div>

    {#if activeTab === 'code' && activePreview}
      <span class="file-label" title={activePreview.filePath}>
        {activePreview.filePath.split('/').pop() ?? activePreview.filePath}
        {#if activePreview.lineStart !== null}
          :{activePreview.lineStart}
          {#if activePreview.lineEnd !== null && activePreview.lineEnd !== activePreview.lineStart}
            –{activePreview.lineEnd}
          {/if}
        {/if}
      </span>
      {#if codePreview?.specRef}
        <button
          class="expand-btn"
          onclick={toggleExpand}
          disabled={codeLoading}
          title={codeExpanded ? 'Show preview (collapse)' : 'Show full range (expand)'}
          aria-label={codeExpanded ? 'Collapse' : 'Expand'}
        >
          {codeExpanded ? '⬆' : '⬇'}
          {#if codeLoading}<span class="loading-dot"></span>{/if}
        </button>
      {/if}
    {/if}

    {#if activeTab === 'terminal' && runState.command}
      <span class="run-status-label" class:error={runState.exitCode !== null && runState.exitCode !== 0}>
        {exitStatusLabel(runState.exitCode, runState.status)}
      </span>
    {/if}

    <button class="close-btn" onclick={onclose} aria-label="Close drawer">✕</button>
  </div>

  <!-- Pane content -->
  <div class="pane-content">
    {#if activeTab === 'code'}
      <div class="code-pane">
        {#if activePreview}
          <MonacoEditor
            value={activePreview.content}
            language={activePreview.language ?? inferLanguage(activePreview.filePath)}
            readOnly={true}
            lineStart={activePreview.previewStart ?? activePreview.lineStart ?? 1}
          />
        {:else}
          <div class="empty-pane">
            <p>Select a code ref on a spec node to preview it here.</p>
          </div>
        {/if}
      </div>

    {:else}
      <!-- Terminal pane -->
      <div class="terminal-pane">
        <!-- Command bar -->
        <div class="cmd-bar">
          <span class="prompt">$</span>
          <input
            class="cmd-input"
            type="text"
            placeholder="Enter command…"
            bind:value={commandInput}
            onkeydown={handleCommandKeydown}
            disabled={isRunning}
            spellcheck="false"
            autocomplete="off"
          />
          {#if isRunning}
            <button class="stop-btn" onclick={handleStop} aria-label="Stop">■ Stop</button>
          {:else}
            <button
              class="run-btn"
              onclick={handleRun}
              disabled={!commandInput.trim() || runLoading}
              aria-label="Run"
            >▶ Run</button>
          {/if}
        </div>

        <!-- Output -->
        <div class="output-scroll" bind:this={outputEl}>
          {#if runState.lines.length === 0 && runState.status === 'idle'}
            <div class="output-empty">Run a command to see output.</div>
          {:else}
            {#each runState.lines as line (line)}
              <div class="output-line" class:stderr={line.stream === 'stderr'}>
                {line.text}
              </div>
            {/each}
            {#if !isRunning && runState.status !== 'idle'}
              <div class="output-exit" class:error={runState.exitCode !== null && runState.exitCode !== 0}>
                — {exitStatusLabel(runState.exitCode, runState.status)} —
              </div>
            {/if}
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  .bottom-drawer {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    background-color: var(--bg-surface);
    border-top: 1px solid var(--border);
    overflow: hidden;
  }

  .drag-handle {
    height: 6px;
    cursor: ns-resize;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background-color: transparent;
    transition: background-color 0.15s;
  }
  .drag-handle:hover, .drag-handle.dragging {
    background-color: var(--element-hover);
  }

  .drag-grip {
    width: 32px;
    height: 2px;
    background-color: var(--border);
    border-radius: 1px;
  }

  .tab-bar {
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--border);
    padding: 0 8px;
    height: 32px;
    flex-shrink: 0;
    gap: 2px;
  }

  .tab {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 0 12px;
    height: 32px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--fg-muted);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
    margin-bottom: -1px;
  }
  .tab:hover { color: var(--fg-primary); }
  .tab.active { color: var(--fg-accent); border-bottom-color: var(--fg-accent); }

  .run-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--status-in-progress, #f0a500);
    animation: pulse 1.2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .tab-spacer { flex: 1; }

  .file-label {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0 4px;
  }

  .expand-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 3px;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s;
  }
  .expand-btn:hover:not(:disabled) { background-color: var(--element-hover); color: var(--fg-primary); }
  .expand-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .loading-dot {
    display: inline-block;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background-color: var(--fg-accent);
    animation: pulse 0.8s ease-in-out infinite;
  }

  .run-status-label {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    padding: 0 8px;
  }
  .run-status-label.error { color: var(--status-blocked, #f85149); }

  .close-btn {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 4px 6px;
    border-radius: 3px;
    transition: all 0.15s;
  }
  .close-btn:hover { background-color: var(--element-hover); color: var(--fg-primary); }

  .pane-content {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .code-pane {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* ── Terminal pane ─────────────────────────────────────────────── */
  .terminal-pane {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .cmd-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    background-color: var(--bg-base);
  }

  .prompt {
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--fg-accent);
    flex-shrink: 0;
    user-select: none;
  }

  .cmd-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--fg-primary);
    font-family: var(--font-mono);
    font-size: 13px;
    caret-color: var(--fg-accent);
    min-width: 0;
  }
  .cmd-input::placeholder { color: var(--fg-muted); }
  .cmd-input:disabled { opacity: 0.5; }

  .run-btn, .stop-btn {
    flex-shrink: 0;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
    border: 1px solid var(--border);
    transition: all 0.15s;
  }

  .run-btn {
    background-color: var(--element-bg);
    color: var(--fg-accent);
  }
  .run-btn:hover:not(:disabled) { background-color: var(--element-hover); }
  .run-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .stop-btn {
    background-color: transparent;
    color: var(--status-blocked, #f85149);
    border-color: var(--status-blocked, #f85149);
  }
  .stop-btn:hover { background-color: color-mix(in srgb, var(--status-blocked, #f85149) 12%, transparent); }

  .output-scroll {
    flex: 1;
    overflow-y: auto;
    padding: 8px 12px;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.5;
    min-height: 0;
  }

  .output-empty {
    color: var(--fg-muted);
    padding: 4px 0;
  }

  .output-line {
    white-space: pre-wrap;
    word-break: break-all;
    color: var(--fg-primary);
  }
  .output-line.stderr { color: var(--status-blocked, #f85149); }

  .output-exit {
    margin-top: 6px;
    color: var(--fg-muted);
    font-size: 11px;
    text-align: center;
    padding: 4px 0;
    border-top: 1px solid var(--border);
  }
  .output-exit.error { color: var(--status-blocked, #f85149); }

  .empty-pane {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--fg-muted);
    font-size: 12px;
  }
  .empty-pane p { margin: 0; }
</style>
