<!--
  AgentDetailPanel.svelte
  Chat-style panel for a root agent — mirrors PrimeChatPanel's look & feel.
  Subscribes to the agent event stream on mount and renders messages,
  tool cards, and state changes in the same visual language as Prime.
-->
<script lang="ts">
  import type { AgentDetailEvent } from '$types/index'
  import { appState, agentStateFromString } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'
  import { onMount, onDestroy, tick } from 'svelte'
  import { marked } from 'marked'
  import PrimeToolCard from '$components/PrimeToolCard.svelte'
  import type { PrimeToolCall } from '$types/index'

  marked.setOptions({ breaks: true, gfm: true })

  interface Props {
    agentId: string
    onclose?: () => void
  }
  const { agentId, onclose }: Props = $props()

  const agent = $derived(appState.agents.get(agentId))
  const events = $derived(appState.detailEvents.get(agentId) ?? [])

  let scrollEl: HTMLElement | undefined = $state()
  let subscribed = $state(false)

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string
  }

  onMount(async () => {
    if (appState.connectionState !== 'ready') return
    try {
      const backlog = await backendClient.agentSubscribe(agentId)
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

  /** Build display items: collapse tokens into message bubbles, pair tool_call + tool_result into PrimeToolCall objects. */
  type DisplayItem =
    | { kind: 'message'; role: string; content: string }
    | { kind: 'streaming'; content: string }
    | { kind: 'tool'; tool: PrimeToolCall }

  const displayItems = $derived.by(() => {
    const out: DisplayItem[] = []
    // Map of callId -> PrimeToolCall for pairing tool_call + tool_result
    const toolMap = new Map<string, PrimeToolCall>()

    for (const ev of events) {
      if (ev.type === 'token') {
        const last = out[out.length - 1]
        if (last?.kind === 'streaming') {
          last.content += ev.text
          continue
        }
        out.push({ kind: 'streaming', content: ev.text })
      } else if (ev.type === 'message') {
        // Finalize any streaming bubble before this message
        const last = out[out.length - 1]
        if (last?.kind === 'streaming') {
          // Convert streaming to final message
          out[out.length - 1] = { kind: 'message', role: 'assistant', content: last.content }
        }
        if (ev.content.trim()) {
          out.push({ kind: 'message', role: ev.role, content: ev.content })
        }
      } else if (ev.type === 'toolCall') {
        // Finalize streaming before tool
        const last = out[out.length - 1]
        if (last?.kind === 'streaming') {
          out[out.length - 1] = { kind: 'message', role: 'assistant', content: last.content }
        }
        const tool: PrimeToolCall = {
          callId: ev.callId,
          toolName: ev.toolName,
          arguments: ev.arguments,
          result: null,
          error: null,
          durationMs: null,
          status: 'running',
        }
        toolMap.set(ev.callId, tool)
        out.push({ kind: 'tool', tool })
      } else if (ev.type === 'toolResult') {
        const tool = toolMap.get(ev.callId)
        if (tool) {
          tool.result = ev.output
          tool.error = ev.error
          tool.durationMs = ev.durationMs
          tool.status = ev.error ? 'error' : 'done'
        }
        // If we didn't see the toolCall (e.g. from backlog), create one
        if (!tool) {
          const orphan: PrimeToolCall = {
            callId: ev.callId,
            toolName: 'tool',
            arguments: {},
            result: ev.output,
            error: ev.error,
            durationMs: ev.durationMs,
            status: ev.error ? 'error' : 'done',
          }
          out.push({ kind: 'tool', tool: orphan })
        }
      }
    }
    return out
  })
</script>

<div class="agent-detail-panel">
  <div class="agent-chat" bind:this={scrollEl}>
    {#if !subscribed}
      <div class="agent-empty">
        <p class="agent-hint">Connecting...</p>
      </div>
    {:else if displayItems.length === 0}
      <div class="agent-empty">
        <span class="agent-icon">●</span>
        <p class="agent-title">{agent?.displayName ?? agentId}</p>
        <p class="agent-hint">Waiting for events...</p>
      </div>
    {:else}
      <div class="agent-messages">
        {#each displayItems as item, i (i)}
          {#if item.kind === 'message'}
            {#if item.role === 'user'}
              <div class="message-row user-wrapper">
                <div class="agent-bubble user">
                  <div class="bubble-content">{@html renderMarkdown(item.content)}</div>
                </div>
              </div>
            {:else}
              <div class="message-row">
                <div class="agent-bubble assistant">
                  <div class="bubble-content">{@html renderMarkdown(item.content)}</div>
                </div>
              </div>
            {/if}
          {:else if item.kind === 'streaming'}
            <div class="agent-bubble assistant streaming">
              <div class="bubble-content">
                {#if item.content}
                  {@html renderMarkdown(item.content)}
                {/if}
                <span class="cursor-blink">|</span>
              </div>
            </div>
          {:else if item.kind === 'tool'}
            <div class="tool-entry">
              <PrimeToolCard tool={item.tool} />
            </div>
          {/if}
        {/each}
      </div>
    {/if}
  </div>

  {#if agent && agent.state !== 'idle' && agent.state !== 'done'}
    <div class="panel-footer">
      <button
        class="stop-btn"
        onclick={() => backendClient.agentStop(agentId)}
      >Stop agent</button>
    </div>
  {/if}
</div>

<style lang="postcss">
  .agent-detail-panel {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .agent-chat {
    flex: 1;
    overflow-y: auto;
    padding: 0;
    display: flex;
    flex-direction: column;
  }

  .agent-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    color: var(--fg-muted);
    text-align: center;
    gap: 6px;
  }

  .agent-icon {
    font-size: 32px;
    color: var(--fg-accent);
    margin-bottom: 8px;
    opacity: 0.6;
  }

  .agent-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--fg-primary);
    text-transform: capitalize;
  }

  .agent-hint {
    margin: 0;
    max-width: 28ch;
    line-height: 1.5;
    font-size: 12px;
  }

  .agent-messages {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .message-row {
    position: relative;
  }

  .user-wrapper {
    background-color: color-mix(in srgb, var(--fg-primary) 4%, transparent);
    padding: 10px 12px;
    border-radius: 6px;
  }

  .agent-bubble {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    font-size: 13px;
    line-height: 1.6;
    word-break: break-word;
    max-width: 640px;
  }

  .agent-bubble.user .bubble-content {
    color: var(--fg-accent);
    font-weight: 500;
  }

  .agent-bubble.assistant,
  .agent-bubble.streaming {
    padding-left: 12px;
  }

  .agent-bubble.assistant .bubble-content,
  .agent-bubble.streaming .bubble-content {
    color: var(--fg-primary);
  }

  .bubble-content {
    margin: 0;
    min-width: 0;
  }

  .bubble-content :global(p) {
    margin: 0 0 0.5em;
  }

  .bubble-content :global(p:last-child) {
    margin-bottom: 0;
  }

  .bubble-content :global(strong) {
    color: var(--fg-primary);
    font-weight: 600;
  }

  .bubble-content :global(code) {
    font-family: var(--font-mono, monospace);
    font-size: 0.88em;
    padding: 2px 5px;
    background-color: var(--element-bg);
    border-radius: 3px;
  }

  .bubble-content :global(pre) {
    margin: 0.6em 0;
    padding: 10px 12px;
    background-color: var(--element-bg);
    border-radius: 4px;
    border: 1px solid var(--border-variant);
    overflow-x: auto;
    font-size: 0.85em;
    line-height: 1.5;
  }

  .bubble-content :global(pre code) {
    padding: 0;
    background: none;
    border-radius: 0;
  }

  .bubble-content :global(ul),
  .bubble-content :global(ol) {
    margin: 0.4em 0;
    padding-left: 1.5em;
  }

  .bubble-content :global(li) {
    margin-bottom: 0.2em;
  }

  .bubble-content :global(blockquote) {
    margin: 0.4em 0;
    padding-left: 10px;
    border-left: 2px solid var(--fg-accent);
    color: var(--fg-muted);
  }

  .bubble-content :global(hr) {
    border: none;
    border-top: 1px solid var(--border-variant);
    margin: 0.8em 0;
  }

  /* ── Streaming cursor ─────────────────────────────────────────────────── */

  .cursor-blink {
    display: inline;
    color: var(--fg-accent);
    animation: blink 0.8s step-end infinite;
    font-weight: 300;
  }

  /* ── Tool entries ─────────────────────────────────────────────────────── */

  .tool-entry {
    padding: 0 12px;
    max-width: 560px;
  }

  /* ── Footer ───────────────────────────────────────────────────────────── */

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

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
</style>
