<!--
  MinionCard.svelte
  Collapsible inline card for a minion agent inside Prime's chat stream.
  Shows task summary when collapsed; full scrollable output when expanded.
-->
<script lang="ts">
  import type { PrimeMinionEntry } from '$types/index'
  import Shimmer from '$components/Shimmer.svelte'

  interface Props {
    minion: PrimeMinionEntry
  }
  const { minion }: Props = $props()

  let expanded = $state(false)

  const isRunning = $derived(minion.status === 'running')
  const isDone = $derived(minion.status === 'done')
  const hasError = $derived(minion.status === 'error')

  /** Truncated task for the header line. */
  const taskSummary = $derived(
    minion.task.length > 80 ? minion.task.slice(0, 80) + '...' : minion.task,
  )

  /** The full result text. */
  const resultText = $derived(minion.result ?? '')
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="minion-card"
  class:running={isRunning}
  class:done={isDone}
  class:error={hasError}
  onclick={() => { expanded = !expanded }}
>
  <div class="minion-header">
    <span class="minion-icon">{isRunning ? '⟳' : hasError ? '✗' : '✓'}</span>
    <span class="minion-label">minion</span>
    <span class="minion-task">{taskSummary}</span>
    <span class="minion-chevron">{expanded ? '▾' : '▸'}</span>
  </div>

  {#if expanded && resultText}
    <div class="minion-detail">
      <span class="minion-section-label">Result</span>
      <pre class="minion-output selectable">{resultText.slice(0, 4000)}{resultText.length > 4000 ? '\n...' : ''}</pre>
    </div>
  {:else if !expanded && isDone && resultText}
    <div class="minion-preview">
      {resultText.slice(0, 120)}{resultText.length > 120 ? '...' : ''}
    </div>
  {/if}

  {#if isRunning}
    <Shimmer />
  {/if}
</div>

<style lang="postcss">
  .minion-card {
    border: 1px solid var(--border-variant);
    border-radius: 6px;
    background-color: var(--element-bg);
    cursor: pointer;
    overflow: hidden;
    transition: border-color 0.15s;
    position: relative;
  }

  .minion-card.running {
    border-color: var(--fg-accent);
  }

  .minion-card.error {
    border-color: var(--status-error);
  }

  .minion-card.done {
    border-color: var(--border-variant);
  }

  .minion-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    font-size: 12px;
  }

  .minion-icon {
    font-size: 11px;
    flex-shrink: 0;
  }

  .minion-card.running .minion-icon {
    color: var(--fg-accent);
    animation: spin 1.2s linear infinite;
  }

  .minion-card.error .minion-icon {
    color: var(--status-error);
  }

  .minion-card.done .minion-icon {
    color: var(--status-done);
  }

  .minion-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }

  .minion-task {
    color: var(--fg-primary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1;
  }

  .minion-chevron {
    font-size: 10px;
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .minion-preview {
    padding: 0 10px 6px;
    font-size: 11px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .minion-detail {
    border-top: 1px solid var(--border-variant);
    padding: 8px 10px;
  }

  .minion-section-label {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
  }

  .minion-output {
    margin: 0;
    font-family: var(--font-mono, monospace);
    font-size: 10px;
    color: var(--fg-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
