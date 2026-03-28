<!--
  4.5 MessageBar.svelte
  Bottom message bar: tier selector + text input for agent launch / steer / queue.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import type { AgentTier } from '$types/index'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  const TIERS: AgentTier[] = ['low', 'medium', 'high']

  let inputEl: HTMLTextAreaElement | undefined = $state()
  let draft = $state('')
  let sending = $state(false)

  const selectedRef = $derived(appState.selectedSpecRef)

  const activeAgent = $derived(
    appState.detailAgentId ? appState.agents.get(appState.detailAgentId) ?? null : null
  )

  const steerableAgent = $derived(
    activeAgent && activeAgent.state !== 'idle' && activeAgent.state !== 'done'
      ? activeAgent
      : null
  )

  const placeholder = $derived(
    steerableAgent
      ? `Steer active agent (Shift+Enter to queue)…`
      : `Launch ${appState.launchTier} agent on ${selectedRef ?? 'a node'}…`
  )

  async function submit() {
    const msg = draft.trim()
    if (!msg || sending) return
    sending = true
    draft = ''

    try {
      if (steerableAgent) {
        // Steer running agent
        await backendClient.agentSteer(steerableAgent.agentId, msg)
      } else {
        if (!selectedRef) return
        // Launch new agent and open detail panel
        const result = await backendClient.agentLaunch(selectedRef, msg, appState.launchTier)
        appState.detailAgentId = result.agentId
      }
    } catch (e) {
      console.error('[MessageBar] send failed:', e)
    } finally {
      sending = false
      await tick()
      if (inputEl) inputEl.style.height = 'auto'
      inputEl?.focus()
    }
  }

  async function submitQueue() {
    const msg = draft.trim()
    if (!msg || !steerableAgent || sending) return
    sending = true
    draft = ''
    try {
      await backendClient.agentQueue(steerableAgent.agentId, msg)
    } catch (e) {
      console.error('[MessageBar] queue failed:', e)
    } finally {
      sending = false
      await tick()
      if (inputEl) inputEl.style.height = 'auto'
      inputEl?.focus()
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && e.shiftKey && steerableAgent) {
      // Shift+Enter = queue (only when agent is active)
      e.preventDefault()
      submitQueue()
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function autoResize(e: Event) {
    const el = e.target as HTMLTextAreaElement
    el.style.height = 'auto'
    el.style.height = el.scrollHeight + 'px'
  }
</script>

<div class="message-bar-shell">
  <!-- Tool brief (ephemeral, from active agent) -->
  {#if steerableAgent?.toolBrief}
    <div class="tool-brief">{steerableAgent.toolBrief}</div>
  {/if}

  <div class="input-row">
    <textarea
      bind:this={inputEl}
      bind:value={draft}
      class="message-input selectable"
      rows="2"
      {placeholder}
      disabled={sending || (!selectedRef && !steerableAgent)}
      onkeydown={onKeydown}
      oninput={autoResize}
      autocomplete="off"
      spellcheck="false"
    ></textarea>

    <div class="message-actions">
      {#if !steerableAgent}
        <div class="tier-radios" role="radiogroup" aria-label="Agent tier">
          {#each TIERS as tier}
            <button
              class="tier-radio"
              class:active={appState.launchTier === tier}
              onclick={() => { appState.launchTier = tier }}
              role="radio"
              aria-checked={appState.launchTier === tier}
            >{tier === 'low' ? 'L' : tier === 'medium' ? 'M' : 'H'}</button>
          {/each}
        </div>
      {:else}
        <div class="agent-indicator">
          <span class="agent-dot"></span>
          <span class="agent-label">{steerableAgent.tier}</span>
        </div>
      {/if}

      <button
        class="send-btn"
        onclick={submit}
        disabled={!draft.trim() || sending || (!selectedRef && !steerableAgent)}
        aria-label="Send"
      >
        {sending ? '…' : '↑'}
      </button>
    </div>
  </div>
</div>

<style lang="postcss">
  .message-bar-shell {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    padding: 8px 10px;
    background-color: var(--bg-surface);
  }

  .tool-brief {
    font-size: 11px;
    color: var(--fg-muted);
    padding: 4px 8px;
    background-color: var(--element-bg);
    border-radius: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    gap: 10px;
  }

  .message-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
  }

  .tier-radios {
    display: flex;
    gap: 0;
    flex-shrink: 0;
  }

  .tier-radio {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--fg-muted);
    font-size: 11px;
    font-weight: 600;
    font-family: var(--font-sans);
    cursor: pointer;
    transition: all 0.1s;
    margin-left: -1px;
  }
  .tier-radio:first-child { margin-left: 0; }
  .tier-radio:hover { background-color: var(--element-hover); color: var(--fg-primary); }
  .tier-radio.active { background-color: var(--element-selected); color: var(--fg-accent); border-color: var(--fg-accent); z-index: 1; }

  .agent-indicator {
    display: flex;
    align-items: center;
    gap: 7px;
    flex-shrink: 0;
    height: 32px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: 0;
    background-color: var(--element-bg);
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
    min-height: calc(2 * 1.4em + 12px);
    max-height: calc(7 * 1.4em + 12px);
    overflow-y: auto;
    resize: none;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 0;
    padding: 6px 10px;
    font-size: 14px;
    line-height: 1.4;
    font-family: var(--font-sans);
    color: var(--fg-primary);
    outline: none;
    transition: border-color 0.15s;
    field-sizing: content;
  }
  .message-input::placeholder { color: var(--fg-muted); }
  .message-input:focus { border-color: var(--fg-accent); }
  .message-input:disabled { opacity: 0.5; cursor: not-allowed; }

  .send-btn {
    width: 32px;
    height: 32px;
    border: 1px solid var(--border);
    border-radius: 0;
    background: var(--bg-base);
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

  @media (max-width: 900px) {
    .input-row {
      flex-wrap: wrap;
    }

    .message-actions {
      width: 100%;
      justify-content: flex-end;
    }

    .tier-field,
    .agent-indicator {
      flex: 1;
      min-width: 0;
    }
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
