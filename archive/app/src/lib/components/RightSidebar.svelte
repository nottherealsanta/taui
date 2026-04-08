<!--
  RightSidebar.svelte — Collapsible right sidebar with switchable panels.

  Panels:
  - Outline: Table of contents for the current file
  - Backlinks: Files that link to the current file
  - Agent: Existing AgentDetailPanel functionality
-->
<script lang="ts">
  import OutlinePanel from '$components/OutlinePanel.svelte'
  import BacklinksPanel from '$components/BacklinksPanel.svelte'
  import AgentDetailPanel from '$components/AgentDetailPanel.svelte'
  import { appState } from '$stores/app-state.svelte'

  type PanelTab = 'outline' | 'backlinks' | 'agent'

  let activePanel: PanelTab = $state('outline')

  const detailAgentId = $derived(appState.detailAgentId)

  // Auto-switch to agent tab when an agent detail opens
  $effect(() => {
    if (detailAgentId !== null) {
      activePanel = 'agent'
    }
  })
</script>

<aside class="right-sidebar">
  <!-- Tab switcher -->
  <div class="sidebar-tabs">
    <button
      class="tab-btn"
      class:active={activePanel === 'outline'}
      onclick={() => { activePanel = 'outline' }}
      title="Outline"
    >Outline</button>
    <button
      class="tab-btn"
      class:active={activePanel === 'backlinks'}
      onclick={() => { activePanel = 'backlinks' }}
      title="Backlinks"
    >Backlinks</button>
    <button
      class="tab-btn"
      class:active={activePanel === 'agent'}
      onclick={() => { activePanel = 'agent' }}
      title="Agent"
    >
      Agent
      {#if detailAgentId}
        <span class="agent-indicator"></span>
      {/if}
    </button>
  </div>

  <!-- Panel content -->
  <div class="panel-content">
    {#if activePanel === 'outline'}
      <OutlinePanel />
    {:else if activePanel === 'backlinks'}
      <BacklinksPanel />
    {:else if activePanel === 'agent'}
      {#if detailAgentId !== null}
        <AgentDetailPanel
          agentId={detailAgentId}
          onclose={() => { appState.detailAgentId = null }}
        />
      {:else}
        <div class="empty-panel">
          <p>No agent active</p>
          <p class="hint">Launch an agent from the message bar</p>
        </div>
      {/if}
    {/if}
  </div>
</aside>

<style lang="postcss">
  .right-sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    background-color: var(--bg-surface);
    overflow: hidden;
  }

  .sidebar-tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .tab-btn {
    flex: 1;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 6px 8px;
    transition: all 0.15s;
    position: relative;
  }

  .tab-btn:hover {
    color: var(--fg-primary);
    background-color: var(--element-hover);
  }

  .tab-btn.active {
    color: var(--fg-primary);
    border-bottom-color: var(--fg-accent);
  }

  .agent-indicator {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--status-in-progress);
    margin-left: 4px;
    vertical-align: middle;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .panel-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .empty-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    gap: 4px;
    color: var(--fg-muted);
    font-size: 12px;
    padding: 20px;
    text-align: center;
  }

  .empty-panel p {
    margin: 0;
  }

  .hint {
    font-size: 11px;
    color: var(--fg-muted);
    opacity: 0.7;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
