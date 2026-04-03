<script lang="ts">
  import SplitPane from '$components/SplitPane.svelte'
  import SpecEditorPane from '$components/SpecEditorPane.svelte'
  import AgentPane from '$components/AgentPane.svelte'

  interface Props {
    agentPaneCollapsed?: boolean
  }

  const { agentPaneCollapsed = false }: Props = $props()
</script>

<section class="main-pane">
  <div class="main-pane-body">
    <SplitPane
      direction="horizontal"
      initialRatio={0.5}
      minSize={280}
      minSecondSize={280}
      maxSize={100000}
      storageKey="taui-main-pane-split"
      collapsed={agentPaneCollapsed}
    >
      {#snippet first()}
        <div class="spec-pane">
          <SpecEditorPane />
        </div>
      {/snippet}

      {#snippet second()}
        <div class="agent-pane-container">
          <AgentPane />
        </div>
      {/snippet}
    </SplitPane>
  </div>
</section>

<style lang="postcss">
  .main-pane {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .main-pane-body {
    display: flex;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .spec-pane {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .agent-pane-container {
    display: flex;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
</style>