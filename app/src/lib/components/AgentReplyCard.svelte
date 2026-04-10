<!--
  AgentReplyCard.svelte
  Inline card for a message posted directly to the user by a sub-agent or root agent.
  Appears in Prime's chat stream with a left-border accent.
-->
<script lang="ts">
  interface Props {
    agentName: string
    message: string
    title?: string | null
  }
  const { agentName, message, title = null }: Props = $props()
</script>

<div class="agent-reply-card">
  <div class="agent-reply-header">
    <span class="agent-reply-dot"></span>
    <span class="agent-reply-name">{agentName}</span>
    {#if title}
      <span class="agent-reply-title">{title}</span>
    {/if}
  </div>
  <div class="agent-reply-message">{message}</div>
</div>

<style lang="postcss">
  .agent-reply-card {
    border-left: 2px solid var(--fg-accent);
    background-color: color-mix(in srgb, var(--fg-accent) 5%, transparent);
    padding: 6px 10px 8px;
    overflow: hidden;
  }

  .agent-reply-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
  }

  .agent-reply-dot {
    display: block;
    width: 6px;
    height: 6px;
    background-color: var(--fg-accent);
    flex-shrink: 0;
    opacity: 0.8;
  }

  .agent-reply-name {
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-accent);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }

  .agent-reply-title {
    font-size: 11px;
    color: var(--fg-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  .agent-reply-message {
    font-size: 12px;
    color: var(--fg-primary);
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
