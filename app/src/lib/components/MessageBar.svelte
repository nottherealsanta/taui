<!--
  4.5 MessageBar.svelte
  Bottom message bar: tier selector + text input for agent launch / steer / queue.
-->
<script lang="ts">
  import type { AgentTier } from '$types/index'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  const TIERS: AgentTier[] = ['junior', 'mid', 'senior']

  let inputEl: HTMLInputElement | undefined = $state()
  let draft = $state('')
  let sending = $state(false)

  const selectedRef = $derived(appState.selectedSpecRef)

  // Active agent on the selected node (if any)
  const activeAgent = $derived(
    selectedRef
      ? [...appState.agents.values()].find(
          (a) => a.specRef === selectedRef && a.state !== 'idle' && a.state !== 'done'
        ) ?? null
      : null
  )

  const placeholder = $derived(
    activeAgent
      ? `Steer agent (Shift+Enter to queue)…`
      : `Launch ${appState.launchTier} agent on ${selectedRef ?? 'a node'}…`
  )

  async function submit() {
    const msg = draft.trim()
    if (!msg || !selectedRef || sending) return
    sending = true
    draft = ''

    try {
      if (activeAgent) {
        // Steer running agent
        await backendClient.agentSteer(activeAgent.agentId, msg)
      } else {
        // Launch new agent and open detail panel
        const result = await backendClient.agentLaunch(selectedRef, msg, appState.launchTier)
        appState.detailAgentId = result.agentId
      }
    } catch (e) {
      console.error('[MessageBar] send failed:', e)
    } finally {
      sending = false
      await import('svelte').then(({ tick }) => tick()).then(() => inputEl?.focus())
    }
  }

  async function submitQueue() {
    const msg = draft.trim()
    if (!msg || !activeAgent || sending) return
    sending = true
    draft = ''
    try {
      await backendClient.agentQueue(activeAgent.agentId, msg)
    } catch (e) {
      console.error('[MessageBar] queue failed:', e)
    } finally {
      sending = false
      await import('svelte').then(({ tick }) => tick()).then(() => inputEl?.focus())
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && e.shiftKey && activeAgent) {
      // Shift+Enter = queue (only when agent is active)
      e.preventDefault()
      submitQueue()
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
</script>

<div class="message-bar">
  <!-- Tool brief (ephemeral, from active agent) -->
  {#if activeAgent?.toolBrief}
    <div class="tool-brief">{activeAgent.toolBrief}</div>
  {/if}

  <div class="input-row">
    <!-- Tier selector (only shown when no active agent) -->
    {#if !activeAgent}
      <div class="tier-selector">
        {#each TIERS as tier}
          <button
            class="tier-btn"
            class:active={appState.launchTier === tier}
            onclick={() => { appState.launchTier = tier }}
            aria-pressed={appState.launchTier === tier}
          >{tier}</button>
        {/each}
      </div>
    {:else}
      <div class="agent-indicator">
        <span class="agent-dot"></span>
        <span class="agent-label">{activeAgent.tier}</span>
      </div>
    {/if}

    <input
      bind:this={inputEl}
      bind:value={draft}
      class="message-input selectable"
      type="text"
      {placeholder}
      disabled={sending || !selectedRef}
      onkeydown={onKeydown}
      autocomplete="off"
      spellcheck="false"
    />

    <button
      class="send-btn"
      onclick={submit}
      disabled={!draft.trim() || !selectedRef || sending}
      aria-label="Send"
    >
      {sending ? '…' : '↑'}
    </button>
  </div>
</div>

<style lang="postcss">
  .message-bar {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
    background-color: var(--bg-surface);
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .tool-brief {
    font-size: 11px;
    color: var(--fg-muted);
    padding: 2px 6px;
    background-color: var(--element-bg);
    border-radius: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .input-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .tier-selector {
    display: flex;
    gap: 2px;
    flex-shrink: 0;
  }

  .tier-btn {
    padding: 2px 8px;
    font-size: 11px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .tier-btn:hover { background-color: var(--element-hover); color: var(--fg-primary); }
  .tier-btn.active { background-color: var(--element-selected); color: var(--fg-accent); border-color: var(--fg-accent); }

  .agent-indicator {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: 3px;
  }

  .agent-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: var(--status-in-progress);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .agent-label { font-size: 11px; color: var(--fg-muted); }

  .message-input {
    flex: 1;
    min-width: 0;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 13px;
    font-family: var(--font-sans);
    color: var(--fg-primary);
    outline: none;
    transition: border-color 0.15s;
  }
  .message-input::placeholder { color: var(--fg-muted); }
  .message-input:focus { border-color: var(--fg-accent); }
  .message-input:disabled { opacity: 0.5; cursor: not-allowed; }

  .send-btn {
    width: 32px;
    height: 32px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    color: var(--fg-muted);
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: all 0.15s;
  }
  .send-btn:hover:not(:disabled) { background-color: var(--fg-accent); color: var(--bg-base); border-color: var(--fg-accent); }
  .send-btn:disabled { opacity: 0.3; cursor: not-allowed; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
