<!--
  PrimeToolCard.svelte
  Collapsible card showing a tool call inside Prime's chat stream.
  Shows tool name + arguments summary when collapsed, full output when expanded.
-->
<script lang="ts">
  import type { PrimeToolCall } from '$types/index'
  import Shimmer from '$components/Shimmer.svelte'

  interface Props {
    tool: PrimeToolCall
  }
  const { tool }: Props = $props()

  let expanded = $state(false)

  const isRunning = $derived(tool.status === 'running')
  const hasError = $derived(tool.status === 'error')

  /** Short summary of arguments for the collapsed view. */
  const argsSummary = $derived.by(() => {
    if (!tool.arguments || typeof tool.arguments !== 'object') return ''
    const obj = tool.arguments as Record<string, unknown>
    const keys = Object.keys(obj)
    if (keys.length === 0) return ''
    // Show first key=value pair, truncated
    const first = keys[0]
    const val = String(obj[first] ?? '').slice(0, 60)
    const suffix = keys.length > 1 ? ` +${keys.length - 1}` : ''
    return `${first}=${val}${suffix}`
  })

  /** Full output text for expanded view. */
  const outputText = $derived(tool.error ?? tool.result ?? '')
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="tool-card"
  class:running={isRunning}
  class:error={hasError}
  class:done={tool.status === 'done'}
  onclick={() => { expanded = !expanded }}
>
  <div class="tool-header">
    <span class="tool-icon">{isRunning ? '⟳' : hasError ? '✗' : '✓'}</span>
    <span class="tool-name">{tool.toolName}</span>
    {#if tool.durationMs != null}
      <span class="tool-duration">{tool.durationMs}ms</span>
    {/if}
    <span class="tool-chevron">{expanded ? '▾' : '▸'}</span>
  </div>

  {#if !expanded && argsSummary}
    <div class="tool-args-summary">{argsSummary}</div>
  {/if}

  {#if expanded}
    <div class="tool-detail">
      <div class="tool-section">
        <span class="tool-section-label">Arguments</span>
        <pre class="tool-pre selectable">{JSON.stringify(tool.arguments, null, 2)}</pre>
      </div>
      {#if outputText}
        <div class="tool-section">
          <span class="tool-section-label">{hasError ? 'Error' : 'Output'}</span>
          <pre class="tool-pre selectable" class:error-text={hasError}>{outputText.slice(0, 2000)}{outputText.length > 2000 ? '\n…' : ''}</pre>
        </div>
      {/if}
    </div>
  {/if}

  {#if isRunning}
    <Shimmer />
  {/if}
</div>

<style lang="postcss">
  .tool-card {
    border: 1px solid var(--border-variant);
    border-radius: 6px;
    background-color: var(--element-bg);
    cursor: pointer;
    overflow: hidden;
    transition: border-color 0.15s;
    position: relative;
  }

  .tool-card.running {
    border-color: var(--fg-accent);
  }

  .tool-card.error {
    border-color: var(--status-error);
  }

  .tool-card.done {
    border-color: var(--border-variant);
  }

  .tool-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    font-size: 12px;
  }

  .tool-icon {
    font-size: 11px;
    flex-shrink: 0;
  }

  .tool-card.running .tool-icon {
    color: var(--fg-accent);
    animation: spin 1.2s linear infinite;
  }

  .tool-card.error .tool-icon {
    color: var(--status-error);
  }

  .tool-card.done .tool-icon {
    color: var(--status-done);
  }

  .tool-name {
    font-weight: 600;
    color: var(--fg-primary);
    white-space: nowrap;
  }

  .tool-duration {
    margin-left: auto;
    font-size: 10px;
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .tool-chevron {
    font-size: 10px;
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .tool-args-summary {
    padding: 0 10px 6px;
    font-size: 11px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .tool-detail {
    border-top: 1px solid var(--border-variant);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .tool-section-label {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
  }

  .tool-pre {
    margin: 0;
    font-family: var(--font-mono, monospace);
    font-size: 10px;
    color: var(--fg-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
  }

  .error-text {
    color: var(--status-error);
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
