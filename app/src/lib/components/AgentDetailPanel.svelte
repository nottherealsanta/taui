<!--
  4.6 AgentDetailPanel.svelte
  Slide-in right panel showing the event stream for an agent.
  Subscribes on open, unsubscribes on close.
  Phase 7: Monaco diff rendering for tool results containing unified diffs.
-->
<script lang="ts">
  import type { AgentDetailEvent } from '$types/index'
  import { appState, agentStateFromString } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'
  import { onMount, onDestroy, tick } from 'svelte'
  import MonacoEditor from './MonacoEditor.svelte'

  interface Props {
    agentId: string
    onclose?: () => void
  }
  const { agentId, onclose }: Props = $props()

  const agent = $derived(appState.agents.get(agentId))
  const events = $derived(appState.detailEvents.get(agentId) ?? [])

  let scrollEl: HTMLElement | undefined = $state()
  let subscribed = $state(false)

  onMount(async () => {
    if (appState.connectionState !== 'ready') return
    try {
      const backlog = await backendClient.agentSubscribe(agentId)
      // Parse backlog events
      const parsed = backlog
        .map((raw) => parseEvent(raw as Record<string, unknown>))
        .filter((e): e is AgentDetailEvent => e !== null)
      appState.setDetailBacklog(agentId, parsed)
      appState.detailAgentId = agentId
      subscribed = true
    } catch (e) {
      console.error('[AgentDetailPanel] subscribe failed', e)
    }
    await scrollToBottom()
  })

  onDestroy(async () => {
    if (subscribed) {
      try { await backendClient.agentUnsubscribe(agentId) } catch { /* ignore */ }
    }
    if (appState.detailAgentId === agentId) {
      appState.detailAgentId = null
    }
  })

  // Auto-scroll to bottom when new events arrive
  $effect(() => {
    void events.length
    scrollToBottom()
  })

  async function scrollToBottom() {
    await tick()
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight
  }

  function parseEvent(raw: Record<string, unknown>): AgentDetailEvent | null {
    const type = raw['type'] as string
    switch (type) {
      case 'message': return { type: 'message', role: (raw['role'] as string) ?? 'assistant', content: (raw['content'] as string) ?? '' }
      case 'tool_call': return { type: 'toolCall', callId: (raw['call_id'] as string) ?? '', toolName: (raw['tool_name'] as string) ?? '', arguments: raw['arguments'] ?? {} }
      case 'tool_result': return { type: 'toolResult', callId: (raw['call_id'] as string) ?? '', output: (raw['output'] as string) ?? null, error: (raw['error'] as string) ?? null, durationMs: (raw['duration_ms'] as number) ?? null }
      case 'token': return { type: 'token', text: (raw['text'] as string) ?? '' }
      case 'state_change': return { type: 'stateChange', state: agentStateFromString((raw['state'] as string) ?? 'idle') }
      default: return null
    }
  }

  // Collapse token events into the last message bubble for display
  const displayEvents = $derived(() => {
    const out: Array<{ kind: string; data: AgentDetailEvent }> = []
    for (const ev of events) {
      if (ev.type === 'token') {
        const last = out[out.length - 1]
        if (last?.kind === 'token-run') {
          ;(last.data as { type: 'message'; role: string; content: string }).content += ev.text
          continue
        }
        out.push({ kind: 'token-run', data: { type: 'message', role: 'assistant', content: ev.text } })
      } else {
        out.push({ kind: ev.type, data: ev })
      }
    }
    return out
  })

  // ── Diff helpers ──────────────────────────────────────────────────────────
  function isDiff(text: string | null | undefined): boolean {
    if (!text) return false
    const t = text.trimStart()
    return (
      t.startsWith('diff --git') ||
      t.startsWith('--- ') ||
      t.startsWith('+++') ||
      (t.includes('\n--- ') && t.includes('\n+++ ')) ||
      (t.includes('\n@@ ') && (t.includes('\n-') || t.includes('\n+')))
    )
  }

  // Track which diff blocks are expanded (by event index)
  let expandedDiffs = $state(new Set<number>())
</script>

<aside class="agent-detail-panel">
  <!-- Header -->
  <div class="panel-header">
    <div class="panel-title">
      <span class="agent-dot" class:active={agent?.state !== 'idle' && agent?.state !== 'done'}></span>
      <span class="agent-id">{agentId}</span>
      {#if agent}
        <span class="agent-tier">{agent.tier}</span>
        <span class="agent-state">{typeof agent.state === 'string' ? agent.state : 'unknown'}</span>
      {/if}
    </div>
    {#if onclose}
      <button class="close-btn" onclick={onclose} aria-label="Close agent panel">✕</button>
    {/if}
  </div>

  <!-- Event stream -->
  <div class="event-stream" bind:this={scrollEl}>
    {#if !subscribed}
      <div class="loading">Connecting…</div>
    {:else if events.length === 0}
      <div class="empty">No events yet.</div>
    {:else}
      {#each displayEvents() as item, i (item.data)}
        {@const ev = item.data}
        {#if ev.type === 'message' || item.kind === 'token-run'}
          <div class="event message" class:user={ev.type === 'message' && 'role' in ev && ev.role === 'user'}>
            <span class="role">{'role' in ev ? ev.role : ''}</span>
            <p class="content selectable">{'content' in ev ? ev.content : ''}</p>
          </div>
        {:else if ev.type === 'toolCall'}
          <div class="event tool-call">
            <span class="tool-name">⚙ {ev.toolName}</span>
            <pre class="tool-args selectable">{JSON.stringify(ev.arguments, null, 2)}</pre>
          </div>
        {:else if ev.type === 'toolResult'}
          {@const text = ev.error ?? ev.output ?? ''}
          {@const hasDiff = isDiff(text)}
          {@const diffExpanded = expandedDiffs.has(i)}
          <div class="event tool-result" class:error={!!ev.error} class:has-diff={hasDiff}>
            <div class="result-header">
              <span class="result-label">{ev.error ? '✗ error' : '✓ result'}</span>
              {#if ev.durationMs !== null}<span class="duration">{ev.durationMs}ms</span>{/if}
              {#if hasDiff}
                <button
                  class="diff-toggle"
                  onclick={() => {
                    if (diffExpanded) { expandedDiffs.delete(i); expandedDiffs = new Set(expandedDiffs) }
                    else { expandedDiffs.add(i); expandedDiffs = new Set(expandedDiffs) }
                  }}
                >{diffExpanded ? 'Hide diff ⬆' : 'Show diff ⬇'}</button>
              {/if}
            </div>
            {#if hasDiff && diffExpanded}
              <div class="diff-editor-wrap">
                <MonacoEditor value={text} language="diff" readOnly={true} lineStart={1} />
              </div>
            {:else}
              <pre class="result-output selectable">{text.slice(0, 800)}{text.length > 800 ? '\n…' : ''}</pre>
            {/if}
          </div>
        {:else if ev.type === 'stateChange'}
          <div class="event state-change">
            <span>→ {typeof ev.state === 'string' ? ev.state : 'unknown'}</span>
          </div>
        {/if}
      {/each}
    {/if}
  </div>

  <!-- Footer: stop button -->
  {#if agent && agent.state !== 'idle' && agent.state !== 'done'}
    <div class="panel-footer">
      <button
        class="stop-btn"
        onclick={() => backendClient.agentStop(agentId)}
      >Stop agent</button>
    </div>
  {/if}
</aside>

<style lang="postcss">
  .agent-detail-panel {
    display: flex;
    flex-direction: column;
    flex: 1;
    width: auto;
    min-width: 0;
    min-height: 0;
    background-color: var(--bg-surface);
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .panel-title {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    overflow: hidden;
  }

  .agent-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--fg-muted);
    flex-shrink: 0;
  }
  .agent-dot.active {
    background-color: var(--status-in-progress);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .agent-id {
    font-size: 12px;
    font-weight: 600;
    color: var(--fg-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .agent-tier, .agent-state {
    font-size: 10px;
    color: var(--fg-muted);
    padding: 1px 5px;
    background: var(--element-bg);
    border-radius: 3px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .close-btn {
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
    padding: 4px 6px;
    border-radius: 3px;
    flex-shrink: 0;
    transition: all 0.15s;
  }
  .close-btn:hover { background-color: var(--element-hover); color: var(--fg-primary); }

  .event-stream {
    flex: 1;
    overflow-y: auto;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .loading, .empty {
    color: var(--fg-muted);
    font-size: 12px;
    padding: 12px;
    text-align: center;
  }

  .event {
    padding: 6px 8px;
    border-radius: 4px;
    font-size: 12px;
    background-color: var(--element-bg);
    border: 1px solid var(--border-variant);
  }

  .event.message { border-color: var(--border); }
  .event.message:not(.user) { margin-top: 6px; }
  .event.message.user { background-color: var(--element-selected); }

  .role {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
  }

  .content {
    margin: 0;
    color: var(--fg-primary);
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .event.tool-call { border-color: var(--fg-accent); }
  .tool-name {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-accent);
    margin-bottom: 3px;
  }
  .tool-args {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--fg-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 120px;
    overflow-y: auto;
  }

  .event.tool-result { border-color: var(--status-done); }
  .event.tool-result.error { border-color: var(--status-error); }

  .result-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 3px;
  }

  .result-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--status-done);
  }
  .error .result-label { color: var(--status-error); }

  .duration {
    font-size: 10px;
    color: var(--fg-muted);
    margin-left: auto;
  }

  .diff-toggle {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--fg-accent);
    font-size: 10px;
    padding: 1px 6px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .diff-toggle:hover { background-color: var(--element-hover); }

  .diff-editor-wrap {
    height: 260px;
    margin-top: 4px;
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid var(--border);
  }

  .result-output {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--fg-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 120px;
    overflow-y: auto;
  }

  .event.state-change {
    background: transparent;
    border-color: transparent;
    color: var(--fg-muted);
    font-size: 11px;
    text-align: center;
    padding: 2px;
  }

  .panel-footer {
    padding: 8px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }

  .stop-btn {
    width: 100%;
    padding: 6px;
    background: transparent;
    border: 1px solid var(--status-error);
    border-radius: 4px;
    color: var(--status-error);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .stop-btn:hover { background-color: var(--status-error); color: #fff; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
