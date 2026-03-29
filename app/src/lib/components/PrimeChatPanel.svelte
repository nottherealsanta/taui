<!--
  PrimeChatPanel.svelte
  Chat panel for the Prime agent — the user's main conversational surface.
  Prime can reply to any message and optionally launch root agents.
-->
<script lang="ts">
  import { appState } from '$stores/app-state.svelte'
  import { tick } from 'svelte'
  import { marked } from 'marked'

  marked.setOptions({ breaks: true, gfm: true })

  let scrollEl: HTMLElement | undefined = $state()

  const messages = $derived(appState.primeMessages)

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string
  }

  $effect(() => {
    void messages.length
    scrollToBottom()
  })

  async function scrollToBottom() {
    await tick()
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight
  }
</script>

<div class="prime-chat" bind:this={scrollEl}>
  {#if messages.length === 0}
    <div class="prime-empty">
      <span class="prime-star">★</span>
      <p class="prime-title">Prime</p>
      <p class="prime-hint">Your main agent. Type a message below to start.</p>
    </div>
  {:else}
    <div class="prime-messages">
      {#each messages as msg, i (i)}
        {#if msg.role === 'user'}
          <div class="user-wrapper">
            <div class="prime-bubble user">
              <div class="bubble-content">{@html renderMarkdown(msg.content)}</div>
            </div>
          </div>
        {:else}
          <div class="prime-bubble assistant">
            <div class="bubble-content">{@html renderMarkdown(msg.content)}</div>
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
    padding: 20px 24px;
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
    gap: 16px;
  }

  .user-wrapper {
    border-top: 1px solid var(--border-variant);
    border-bottom: 1px solid var(--border-variant);
    padding: 12px 0;
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

  .prime-bubble.assistant .bubble-content {
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
</style>
