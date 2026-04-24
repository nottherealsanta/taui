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
    agentColor?: string
  }
  const { tool, agentColor = 'var(--fg-accent)' }: Props = $props()

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
  style:--tool-agent-color={agentColor}
  onclick={() => { expanded = !expanded }}
>
  {#if isRunning}
    <div class="pulse-square"></div>
  {/if}

  <div class="tool-header">
    <span class="tool-icon" class:running={isRunning} class:error={hasError} class:done={tool.status === 'done'}>
      <span class="icon-square"></span>
    </span>
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

  /* Pulsing large translucent square overlay, colored by agent */
  .pulse-square {
    position: absolute;
    inset: -4px;
    border-radius: 4px;
    background-color: color-mix(in srgb, var(--tool-agent-color) 18%, transparent);
    animation: pulse-square 2s ease-in-out infinite;
    pointer-events: none;
  }

  @keyframes pulse-square {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.35; transform: scale(1.04); }
  }

  .tool-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 1px 0;
    font-size: 12px;
    line-height: 1;
    position: relative; /* sit above the pulse overlay */
    z-index: 1;
  }

  .tool-icon {
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

  .tool-icon.running .icon-square {
    background-color: var(--tool-agent-color);
    animation: square-breathe 2s ease-in-out infinite;
  }

  .tool-icon.error .icon-square {
    background-color: var(--status-error);
  }

  .tool-icon.done .icon-square {
    background-color: var(--fg-muted);
    opacity: 0.5;
  }

  @keyframes square-breathe {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.4; transform: scale(0.7); }
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
    position: relative;
    z-index: 1;
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
</style>
