<!--
  FrontmatterProperties.svelte — YAML frontmatter property display/editor.

  Shown at the top of the editor pane when a file has YAML frontmatter.
  Renders each field as a labeled row with appropriate formatting.
-->
<script lang="ts">
  interface Props {
    frontmatter: Record<string, unknown>
    tabId?: string
  }
  const { frontmatter }: Props = $props()

  let collapsed = $state(false)

  function formatValue(value: unknown): string {
    if (value === null || value === undefined) return '—'
    if (Array.isArray(value)) return value.join(', ')
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  }

  function getValueClass(key: string, value: unknown): string {
    if (key === 'status') {
      const s = String(value).toLowerCase()
      if (s === 'done' || s === 'complete') return 'status-done'
      if (s === 'in_progress' || s === 'in-progress') return 'status-progress'
      if (s === 'draft') return 'status-draft'
      if (s === 'blocked') return 'status-blocked'
    }
    if (Array.isArray(value)) return 'array-value'
    return ''
  }

  const entries = $derived(Object.entries(frontmatter))
</script>

<div class="frontmatter-props" class:collapsed>
  <button
    class="toggle-btn"
    onclick={() => { collapsed = !collapsed }}
    aria-label={collapsed ? 'Expand properties' : 'Collapse properties'}
  >
    <span class="toggle-icon">{collapsed ? '▸' : '▾'}</span>
    <span class="toggle-label">Properties</span>
    <span class="prop-count">{entries.length}</span>
  </button>

  {#if !collapsed}
    <div class="props-grid">
      {#each entries as [key, value] (key)}
        <div class="prop-row">
          <span class="prop-key">{key}</span>
          <span class="prop-value {getValueClass(key, value)}">
            {#if Array.isArray(value)}
              <span class="tags">
                {#each value as tag}
                  <span class="tag">{tag}</span>
                {/each}
              </span>
            {:else}
              {formatValue(value)}
            {/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style lang="postcss">
  .frontmatter-props {
    border-bottom: 1px solid var(--border-variant);
    background-color: var(--bg-surface);
    flex-shrink: 0;
  }

  .toggle-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 6px 12px;
    text-align: left;
    transition: background-color 0.1s;
  }

  .toggle-btn:hover {
    background-color: var(--element-hover);
  }

  .toggle-icon {
    font-size: 10px;
    width: 10px;
    flex-shrink: 0;
  }

  .toggle-label {
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .prop-count {
    font-size: 10px;
    background: var(--element-bg);
    border-radius: 8px;
    padding: 0 5px;
    margin-left: auto;
  }

  .props-grid {
    padding: 4px 12px 8px;
  }

  .prop-row {
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 2px 0;
    font-size: 12px;
  }

  .prop-key {
    color: var(--fg-muted);
    font-weight: 500;
    min-width: 80px;
    flex-shrink: 0;
    font-size: 11px;
  }

  .prop-value {
    color: var(--fg-primary);
    font-family: var(--font-mono);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .prop-value.status-done { color: var(--status-done); }
  .prop-value.status-progress { color: var(--status-in-progress); }
  .prop-value.status-draft { color: var(--status-draft); }
  .prop-value.status-blocked { color: var(--status-blocked); }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
  }

  .tag {
    background: var(--element-bg);
    border: 1px solid var(--border-variant);
    border-radius: 3px;
    padding: 0 5px;
    font-size: 10px;
    color: var(--fg-accent);
  }
</style>
