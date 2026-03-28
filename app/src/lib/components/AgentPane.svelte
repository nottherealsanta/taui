<script lang="ts">
  import AgentDetailPanel from '$components/AgentDetailPanel.svelte'
  import MessageBar from '$components/MessageBar.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { markdownLineLabel } from '$lib/utils/specs'

  let activePane = $state<string | null>(null)

  const agentTabs = $derived.by(() => {
    return [...appState.agents.values()].filter((agent) => agent.state !== 'idle')
  })

  const activeAgentId = $derived.by(() => {
    if (activePane === null) return null
    return agentTabs.some((agent) => agent.agentId === activePane) ? activePane : null
  })

  $effect(() => {
    const tabs = agentTabs
    if (tabs.length === 0) {
      activePane = null
      appState.detailAgentId = null
      return
    }

    if (appState.detailAgentId && tabs.some((agent) => agent.agentId === appState.detailAgentId)) {
      activePane = appState.detailAgentId
      return
    }

    if (activePane !== null && tabs.some((agent) => agent.agentId === activePane)) {
      return
    }

    activePane = null
  })

  const activeAgent = $derived(
    activeAgentId ? appState.agents.get(activeAgentId) ?? null : null
  )

  function labelForAgent(specRef: string): string {
    const nodeId = appState.specRefIndex.get(specRef)
    if (nodeId === undefined) return specRef.split('#').pop() ?? specRef
    return markdownLineLabel(appState.nodes[nodeId]?.markdown ?? specRef)
  }

  function selectAgent(agentId: string | null) {
    activePane = agentId
    appState.detailAgentId = agentId
  }
</script>

<section class="agent-pane">
  <div class="agent-tabs" role="tablist">
    <button
      class="agent-tab launch-tab"
      class:active={activeAgentId === null}
      onclick={() => selectAgent(null)}
      aria-pressed={activeAgentId === null}
    >New</button>

    {#each agentTabs as agent (agent.agentId)}
      <button
        class="agent-tab"
        class:active={activeAgentId === agent.agentId}
        onclick={() => selectAgent(agent.agentId)}
        aria-pressed={activeAgentId === agent.agentId}
        title={agent.agentId}
      >
        <span class="agent-state-dot"></span>
        <span class="agent-tab-label">{labelForAgent(agent.specRef)}</span>
      </button>
    {/each}
  </div>

  <div class="agent-body">
    {#if activeAgent}
      <AgentDetailPanel agentId={activeAgent.agentId} onclose={() => selectAgent(null)} />
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

  .agent-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 180px;
    min-width: 0;
    padding: 0 10px;
    height: 33px;
    border: none;
    border-right: 1px solid var(--border-variant);
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
  }

  .agent-tab:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .agent-tab.active {
    background-color: var(--bg-surface);
    color: var(--fg-primary);
    border-bottom: 2px solid var(--fg-accent);
  }

  .launch-tab {
    font-weight: 600;
  }

  .agent-state-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    flex-shrink: 0;
    background-color: var(--status-in-progress);
  }

  .agent-tab-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

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
    border-top: 1px solid var(--border);
  }

  .empty-hint {
    margin: 0;
    max-width: 28ch;
    line-height: 1.5;
  }
</style>