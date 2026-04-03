<!--
  PrimeChatPanel.svelte
  Chat panel for the Prime agent — the user's main conversational surface.
  Renders streaming text, tool call cards, sub-agent cards, and agent-launch notices.
-->
<script lang="ts">
  import { appState } from '$stores/app-state.svelte'
  import { tick } from 'svelte'
  import { marked } from 'marked'
  import PrimeToolCard from '$components/PrimeToolCard.svelte'
  import SubAgentCard from '$components/SubAgentCard.svelte'

  marked.setOptions({ breaks: true, gfm: true })

  let scrollEl: HTMLElement | undefined = $state()

  const entries = $derived(appState.primeChatEntries)

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string
  }

  $effect(() => {
    void entries.length
    // Also react to streaming buffer updates
    void appState.primeStreamBuffer
    scrollToBottom()
  })

  async function scrollToBottom() {
    await tick()
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight
  }
</script>

<div class="prime-chat" bind:this={scrollEl}>
  {#if entries.length === 0}
    <div class="prime-empty">
      <span class="prime-star">★</span>
      <p class="prime-title">Prime</p>
      <p class="prime-hint">Your main agent. Type a message below to start.</p>
    </div>
  {:else}
    <div class="prime-messages">
      {#each entries as entry, i (i)}
        {#if entry.kind === 'user'}
          <div class="user-wrapper">
            <div class="prime-bubble user">
              <div class="bubble-content">{@html renderMarkdown(entry.content)}</div>
            </div>
          </div>
        {:else if entry.kind === 'assistant'}
          <div class="prime-bubble assistant">
            <div class="bubble-content">{@html renderMarkdown(entry.content)}</div>
          </div>
        {:else if entry.kind === 'assistant-streaming'}
          <div class="prime-bubble assistant streaming">
            <div class="bubble-content">
              {#if entry.content}
                {@html renderMarkdown(entry.content)}
              {/if}
              <span class="cursor-blink">|</span>
            </div>
          </div>
        {:else if entry.kind === 'context-divider'}
          <div class="context-divider" role="separator" aria-label={entry.label}>
            <span>{entry.label}</span>
          </div>
        {:else if entry.kind === 'tool'}
          <div class="tool-entry">
            <PrimeToolCard tool={entry.tool} />
          </div>
        {:else if entry.kind === 'sub_agent'}
          <div class="sub-agent-entry">
            <SubAgentCard subAgent={entry.subAgent} />
          </div>
        {:else if entry.kind === 'agent-launched'}
          <div class="agent-launched-entry">
            <span class="agent-launched-icon">→</span>
            <span class="agent-launched-text">
              Launched <strong>{entry.displayName}</strong>: {entry.task}
            </span>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style lang="postcss">
  .prime-chat {
    flex: 1;
    overflow-y: auto;
    padding: 0;
    display: flex;
    flex-direction: column;
  }

  .prime-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    color: var(--fg-muted);
    text-align: center;
    gap: 6px;
  }

  .prime-star {
    font-size: 32px;
    color: var(--fg-accent);
    margin-bottom: 8px;
    opacity: 0.6;
  }

  .prime-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--fg-primary);
  }

  .prime-hint {
    margin: 0;
    max-width: 28ch;
    line-height: 1.5;
    font-size: 12px;
  }

  .prime-messages {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .user-wrapper {
    background-color: color-mix(in srgb, var(--fg-primary) 4%, transparent);
    padding: 10px 12px;
    border-radius: 6px;
  }

  .prime-bubble {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    font-size: 13px;
    line-height: 1.6;
    word-break: break-word;
    max-width: 640px;
  }

  .prime-bubble.user .bubble-content {
    color: var(--fg-accent);
    font-weight: 500;
  }

  .prime-bubble.assistant,
  .prime-bubble.streaming {
    padding-left: 12px;
  }

  .prime-bubble.assistant .bubble-content,
  .prime-bubble.streaming .bubble-content {
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

  .context-divider {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 10px 0 6px;
    color: var(--fg-muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    opacity: 0.85;
  }

  .context-divider::before,
  .context-divider::after {
    content: '';
    height: 1px;
    background: var(--border-variant);
    flex: 1;
    min-width: 20px;
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }

  /* ── Tool entries ─────────────────────────────────────────────────────── */

  .tool-entry {
    padding: 0 12px;
    max-width: 560px;
  }

  /* ── Sub-agent entries ───────────────────────────────────────────────────────────── */

  .sub-agent-entry {
    padding: 0 12px;
    max-width: 560px;
  }

  /* ── Agent-launched entries ────────────────────────────────────────────── */

  .agent-launched-entry {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .agent-launched-icon {
    color: var(--fg-accent);
    flex-shrink: 0;
  }

  .agent-launched-text :global(strong) {
    color: var(--fg-accent);
    font-weight: 600;
    text-transform: capitalize;
  }
</style>
