<!--
  SubAgentCard.svelte
  Collapsible inline card for a sub-agent inside Prime's chat stream.
  Shows task summary when collapsed; full scrollable output when expanded.
-->
<script lang="ts">
  import type { PrimeSubAgentEntry } from '$types/index'
  import Shimmer from '$components/Shimmer.svelte'

  interface Props {
    subAgent: PrimeSubAgentEntry
  }
  const { subAgent }: Props = $props()

  let expanded = $state(false)

  const isRunning = $derived(subAgent.status === 'running')
  const isDone = $derived(subAgent.status === 'done')
  const hasError = $derived(subAgent.status === 'error')

  /** Truncated task for the header line. */
  const taskSummary = $derived(
    subAgent.task.length > 80 ? subAgent.task.slice(0, 80) + '...' : subAgent.task,
  )

  /** The full result text. */
  const resultText = $derived(subAgent.result ?? '')
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="sub-agent-card"
  class:running={isRunning}
  class:done={isDone}
  class:error={hasError}
  onclick={() => { expanded = !expanded }}
>
  <div class="sub-agent-header">
    <span class="sub-agent-icon" class:running={isRunning} class:error={hasError} class:done={isDone}>
      <span class="icon-square"></span>
    </span>
    <span class="sub-agent-label">sub_agent</span>
    <span class="sub-agent-task">{taskSummary}</span>
    <span class="sub-agent-chevron">{expanded ? '▾' : '▸'}</span>
  </div>

  {#if expanded && resultText}
    <div class="sub-agent-detail">
      <span class="sub-agent-section-label">Result</span>
      <pre class="sub-agent-output selectable">{resultText.slice(0, 4000)}{resultText.length > 4000 ? '\n...' : ''}</pre>
    </div>
  {:else if !expanded && isDone && resultText}
    <div class="sub-agent-preview">
      {resultText.slice(0, 120)}{resultText.length > 120 ? '...' : ''}
    </div>
  {/if}

  {#if isRunning}
    <Shimmer />
  {/if}
</div>

<style lang="postcss">
  .sub-agent-card {
    background-color: color-mix(in srgb, var(--fg-accent) 4%, transparent);
    border-left: 2px solid var(--border-variant);
    cursor: pointer;
    overflow: hidden;
    transition: border-color 0.15s, background-color 0.15s;
    position: relative;
  }

  .sub-agent-card.running {
    border-left-color: var(--fg-accent);
    background-color: color-mix(in srgb, var(--fg-accent) 6%, transparent);
  }

  .sub-agent-card.error {
    border-left-color: var(--status-error);
    background-color: color-mix(in srgb, var(--status-error) 4%, transparent);
  }

  .sub-agent-card.done {
    border-left-color: var(--border-variant);
  }

  .sub-agent-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    font-size: 12px;
  }

  .sub-agent-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 14px;
    height: 14px;
  }

  .icon-square {
    display: block;
    width: 7px;
    height: 7px;
    background-color: var(--fg-muted);
    transition: background-color 0.2s;
  }

  .sub-agent-icon.running .icon-square {
    background-color: var(--fg-accent);
    animation: square-breathe 2s ease-in-out infinite;
  }

  .sub-agent-icon.error .icon-square {
    background-color: var(--status-error);
  }

  .sub-agent-icon.done .icon-square {
    background-color: var(--status-done);
    opacity: 0.6;
  }

  @keyframes square-breathe {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.4; transform: scale(0.7); }
  }

  .sub-agent-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }

  .sub-agent-task {
    color: var(--fg-primary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1;
  }

  .sub-agent-chevron {
    font-size: 10px;
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .sub-agent-preview {
    padding: 0 10px 5px;
    font-size: 11px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sub-agent-detail {
    border-top: 1px solid var(--border-variant);
    padding: 8px 10px;
  }

  .sub-agent-section-label {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
  }

  .sub-agent-output {
    margin: 0;
    font-family: var(--font-mono, monospace);
    font-size: 10px;
    color: var(--fg-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
  }
</style>
