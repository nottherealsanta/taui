<!--
  4.7 MetadataRow.svelte
  Displays verification, depends_on, related_to for a spec node.
  code_refs are rendered inline in the tree via CodeRefRow.
-->
<script lang="ts">
  import type { NodeId } from '$types/index'
  import { appState } from '$stores/app-state.svelte'

  interface Props {
    nodeId: NodeId
  }
  const { nodeId }: Props = $props()

  const node = $derived(appState.nodes[nodeId])
  const verification = $derived(node?.verification ?? null)
  const dependsOn = $derived(node?.dependsOn ?? [])
  const relatedTo = $derived(node?.relatedTo ?? [])

  const hasMetadata = $derived(
    verification !== null || dependsOn.length > 0 || relatedTo.length > 0
  )

  let expanded = $state(false)
</script>

{#if hasMetadata}
  <div class="metadata-row">
    <button
      class="toggle-btn"
      onclick={() => { expanded = !expanded }}
      aria-expanded={expanded}
    >
      <span class="toggle-chevron">{expanded ? '▾' : '▸'}</span>
      <span class="toggle-label">metadata</span>
      <span class="meta-summary">
        {#if verification}<span class="tag">verify</span>{/if}
        {#if dependsOn.length}<span class="tag">deps:{dependsOn.length}</span>{/if}
      </span>
    </button>

    {#if expanded}
      <div class="metadata-content">
        {#if verification}
          <div class="meta-section">
            <span class="meta-label">verification</span>
            <span class="meta-value">{verification}</span>
          </div>
        {/if}

        {#if dependsOn.length > 0}
          <div class="meta-section">
            <span class="meta-label">depends on</span>
            <div class="meta-items">
              {#each dependsOn as dep}
                <span class="ref-chip">{dep}</span>
              {/each}
            </div>
          </div>
        {/if}

        {#if relatedTo.length > 0}
          <div class="meta-section">
            <span class="meta-label">related to</span>
            <div class="meta-items">
              {#each relatedTo as rel}
                <span class="ref-chip">{rel}</span>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style lang="postcss">
  .metadata-row {
    margin: 2px 4px;
    border-radius: 4px;
    overflow: hidden;
    font-size: 11px;
  }

  .toggle-btn {
    display: flex;
    align-items: center;
    gap: 5px;
    width: 100%;
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--fg-muted);
    padding: 3px 6px;
    border-radius: 4px;
    text-align: left;
    transition: background-color 0.1s;
  }
  .toggle-btn:hover { background-color: var(--element-hover); }

  .toggle-chevron { font-size: 9px; }
  .toggle-label { font-weight: 500; }

  .meta-summary {
    display: flex;
    gap: 4px;
    margin-left: auto;
  }

  .tag {
    padding: 1px 5px;
    background-color: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 10px;
    color: var(--fg-muted);
  }

  .metadata-content {
    padding: 4px 10px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    border-left: 2px solid var(--border);
    margin-left: 12px;
  }

  .meta-section {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .meta-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .meta-value {
    color: var(--fg-primary);
  }

  .meta-items {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .ref-chip {
    padding: 2px 7px;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--fg-muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
</style>
