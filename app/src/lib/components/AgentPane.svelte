<script lang="ts">
  import AgentDetailPanel from '$components/AgentDetailPanel.svelte'
  import PrimeChatPanel from '$components/PrimeChatPanel.svelte'
  import MessageBar from '$components/MessageBar.svelte'
  import Shimmer from '$components/Shimmer.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'
  import { PRIME_AGENT_ID, AGENT_COLOR_HEX, agentStateIsActive } from '$types/index'

  const AGENT_FALLBACK_PALETTE = ['#3ab6e4', '#72e93a', '#f5d700', '#da63de', '#ff5a00'] as const

  /** Only root agents (not sub-agents) get tabs; hide idle agents. */
  const agentTabs = $derived.by(() => {
    return [...appState.agents.values()].filter(
      (agent) => agent.state !== 'idle' && agent.agentType === 'root',
    )
  })

  const isPrime = $derived(appState.detailAgentId === PRIME_AGENT_ID)

  /** The agent to display — derived directly from detailAgentId + agents map.
   *  No intermediate $effect needed; derivations are synchronous in Svelte 5. */
  const activeAgentId = $derived.by(() => {
    const id = appState.detailAgentId
    if (!id || id === PRIME_AGENT_ID) return null
    // Show panel if the agent exists in our map (any non-idle state)
    const agent = appState.agents.get(id)
    if (agent && agent.state !== 'idle') return id
    return null
  })

  const activeAgent = $derived(
    activeAgentId ? appState.agents.get(activeAgentId) ?? null : null
  )

  /** The agent ID whose tab currently has a pending force-close confirmation. */
  let pendingCloseAgentId: string | null = $state(null)

  function hashString(value: string): number {
    let hash = 0
    for (let i = 0; i < value.length; i += 1) {
      hash = (hash << 5) - hash + value.charCodeAt(i)
      hash |= 0
    }
    return Math.abs(hash)
  }

  /** Resolve an accent color; unknown names are deterministically bucketed by agentId. */
  function colorForAgent(displayName: string, agentId: string): string {
    const named = AGENT_COLOR_HEX[displayName.toLowerCase()]
    if (named) return named
    const idx = hashString(agentId) % AGENT_FALLBACK_PALETTE.length
    return AGENT_FALLBACK_PALETTE[idx]
  }

  function selectAgent(agentId: string | null) {
    pendingCloseAgentId = null
    appState.detailAgentId = agentId
  }

  /**
   * Close a root agent tab.
   *
   * - If the agent is still active and `force` is false, show the inline
   *   confirmation popover instead of closing immediately.
   * - If `force` is true (or the agent is not active), stop the backend
   *   runner (if needed), call agent/close to clean up server-side resources,
   *   then remove the agent from local state.
   */
  async function closeAgent(agentId: string, force: boolean = false) {
    const agent = appState.agents.get(agentId)
    if (!agent) return

    if (agentStateIsActive(agent.state) && !force) {
      // Show warning popover anchored to this tab
      pendingCloseAgentId = agentId
      return
    }

    // Dismiss any open popover
    pendingCloseAgentId = null

    // Force-stop the backend runner if still active
    if (agentStateIsActive(agent.state)) {
      try { await backendClient.agentStop(agentId) } catch { /* ignore */ }
    }

    // Clean up backend resources (event buffers, subscriptions, locks, questions)
    try { await backendClient.agentClose(agentId) } catch { /* ignore */ }

    // Remove from local reactive state; switches to Prime if this was selected
    appState.removeAgent(agentId)
  }

  function handlePopoverKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape' && pendingCloseAgentId !== null) {
      pendingCloseAgentId = null
    }
  }
</script>

<svelte:window onkeydown={handlePopoverKeyDown} />

<section class="agent-pane">
  <div class="agent-tabs" role="tablist">
    <button
      class="agent-tab prime-tab"
      class:active={isPrime}
      onclick={() => selectAgent(PRIME_AGENT_ID)}
      aria-pressed={isPrime}
      title="Prime"
      style:--agent-color="var(--prime-accent)"
    >★</button>

    {#each agentTabs as agent (agent.agentId)}
      {@const agentColor = colorForAgent(agent.displayName, agent.agentId)}
      {@const isActive = agentStateIsActive(agent.state)}
      {@const isPendingClose = pendingCloseAgentId === agent.agentId}
      <div
        class="agent-tab-wrapper"
        class:active={activeAgentId === agent.agentId}
        style:--agent-color={agentColor}
      >
        <button
          class="agent-tab"
          class:active={activeAgentId === agent.agentId}
          onclick={() => selectAgent(agent.agentId)}
          aria-pressed={activeAgentId === agent.agentId}
          title={agent.displayName}
          style:--agent-color={agentColor}
        >
          <span class="agent-state-dot" class:pulsing={isActive} style:background-color={agentColor}></span>
          <span class="agent-tab-label">{agent.displayName}</span>
          {#if isActive}
            <Shimmer color={agentColor} />
          {/if}
        </button>
        <button
          class="tab-close-btn"
          onclick={() => closeAgent(agent.agentId)}
          aria-label="Close {agent.displayName} agent"
          title={isActive ? 'Close (agent is running)' : 'Close'}
        >✕</button>

        {#if isPendingClose}
          <!-- Backdrop to dismiss popover on click-outside -->
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="close-popover-backdrop" onclick={() => pendingCloseAgentId = null}></div>
          <div class="close-confirm-popover" role="alertdialog" aria-label="Agent is still running">
            <p class="popover-warning">Agent is still running</p>
            <div class="popover-actions">
              <button class="popover-cancel" onclick={() => pendingCloseAgentId = null}>Cancel</button>
              <button class="popover-force" onclick={() => closeAgent(agent.agentId, true)}>Force close</button>
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>

  <div class="agent-body selectable">
    {#if isPrime}
      <PrimeChatPanel />
    {:else if activeAgent}
      <AgentDetailPanel agentId={activeAgent.agentId} onclose={() => selectAgent(PRIME_AGENT_ID)} />
    {:else}
      <div class="agent-empty-state">
        <p class="empty-title">Ready for a new agent</p>
        <p class="empty-hint">Select a spec heading on the left, then use the message bar to launch an agent.</p>
      </div>
    {/if}
  </div>

  <div class="agent-message-bar">
    <MessageBar />
  </div>
</section>

<style lang="postcss">
  .agent-pane {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    background-color: var(--bg-base);
    overflow: hidden;
  }

  .agent-tabs {
    display: flex;
    align-items: stretch;
    gap: 0;
    min-height: 33px;
    border-bottom: 1px solid var(--border);
    background-color: var(--bg-base);
    overflow-x: auto;
  }

  /* Wrapper provides the positioning context for the confirmation popover. */
  .agent-tab-wrapper {
    position: relative;
    display: inline-flex;
    align-items: stretch;
    border-right: 1px solid var(--border-variant);
  }

  /* Active wrapper gets the colored bottom border. */
  .agent-tab-wrapper.active {
    border-bottom: 2px solid var(--agent-color, var(--fg-accent));
  }

  .agent-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 160px;
    min-width: 0;
    padding: 0 4px 0 10px;
    height: 33px;
    border: none;
    border-right: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
    position: relative;
    overflow: hidden;
  }

  .agent-tab-wrapper:hover .agent-tab,
  .agent-tab-wrapper:hover .tab-close-btn {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .agent-tab.active {
    background-color: var(--bg-surface);
    color: var(--fg-primary);
  }

  .prime-tab {
    font-size: 14px;
    color: var(--fg-muted);
    padding: 0 10px;
  }

  .prime-tab.active {
    color: var(--prime-accent);
  }

  .agent-state-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    flex-shrink: 0;
  }

  .agent-state-dot.pulsing {
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .agent-tab-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-transform: capitalize;
  }

  /* ── Tab close button ───────────────────────────────────────────────────── */

  .tab-close-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 22px;
    height: 33px;
    padding: 0;
    border: none;
    border-radius: 0;
    background: transparent;
    color: var(--fg-muted);
    font-size: 10px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.1s, background-color 0.1s, color 0.1s;
  }

  /* Show close button on wrapper hover or when tab is active */
  .agent-tab-wrapper:hover .tab-close-btn,
  .agent-tab-wrapper.active .tab-close-btn {
    opacity: 1;
  }

  .tab-close-btn:hover {
    background-color: color-mix(in srgb, var(--status-error) 15%, transparent) !important;
    color: var(--status-error) !important;
  }

  /* ── Close confirmation popover ─────────────────────────────────────────── */

  /* Full-screen transparent backdrop to catch click-outside */
  .close-popover-backdrop {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .close-confirm-popover {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 100;
    min-width: 180px;
    padding: 10px 12px;
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  }

  .popover-warning {
    margin: 0 0 8px;
    font-size: 12px;
    color: var(--fg-primary);
    font-weight: 500;
    white-space: nowrap;
  }

  .popover-warning::before {
    content: '⚠ ';
    color: var(--status-warn, #f5a623);
  }

  .popover-actions {
    display: flex;
    gap: 6px;
  }

  .popover-cancel,
  .popover-force {
    flex: 1;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    transition: background-color 0.1s, color 0.1s;
  }

  .popover-cancel {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--fg-muted);
  }

  .popover-cancel:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .popover-force {
    background: transparent;
    border: 1px solid var(--status-error);
    color: var(--status-error);
  }

  .popover-force:hover {
    background-color: var(--status-error);
    color: #fff;
  }

  /* ── Body / empty state ─────────────────────────────────────────────────── */

  .agent-body {
    flex: 1;
    display: flex;
    min-height: 0;
    overflow: hidden;
  }

  .agent-empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    height: 100%;
    padding: 24px;
    color: var(--fg-muted);
    text-align: center;
  }

  .empty-title {
    margin: 0 0 8px;
    font-size: 14px;
    color: var(--fg-primary);
  }

  .agent-message-bar {
    flex-shrink: 0;
    padding: 0px;
    position: relative;
  }

  .empty-hint {
    margin: 0;
    max-width: 28ch;
    line-height: 1.5;
  }
</style>
