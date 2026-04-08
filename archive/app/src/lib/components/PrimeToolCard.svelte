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
  </div>

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
    width: 100%;
    cursor: pointer;
    overflow: hidden;
    position: relative;
  }

  .tool-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 1px 0;
    font-size: 12px;
    line-height: 1;
  }

  .tool-icon {
    font-size: 11px;
    flex-shrink: 0;
  }

  .tool-card.running .tool-icon {
    color: var(--fg-muted);
    animation: spin 1.2s linear infinite;
  }

  .tool-card.error .tool-icon {
    color: var(--status-error);
  }

  .tool-card.done .tool-icon {
    color: var(--fg-muted);
  }

  .tool-name {
    font-weight: 500;
    color: var(--fg-muted);
    white-space: nowrap;
  }

  .tool-detail {
    padding: 4px 0;
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
