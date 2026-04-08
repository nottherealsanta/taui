<!--
  4.10 StatusBadge.svelte
  Colored dot + label for a spec node status value.
-->
<script lang="ts">
  interface Props {
    status: string | null
  }
  const { status }: Props = $props()

  const config: Record<string, { label: string; color: string }> = {
    draft:       { label: 'draft',       color: 'var(--status-draft)' },
    ready:       { label: 'ready',       color: 'var(--status-ready)' },
    in_progress: { label: 'in progress', color: 'var(--status-in-progress)' },
    done:        { label: 'done',        color: 'var(--status-done)' },
    blocked:     { label: 'blocked',     color: 'var(--status-blocked)' },
  }

  const info = $derived(status ? (config[status] ?? { label: status, color: 'var(--fg-muted)' }) : null)
</script>

{#if info}
  <span class="badge" title={info.label}>
    <span class="dot" style:background-color={info.color}></span>
    <span class="label">{info.label}</span>
  </span>
{/if}

<style lang="postcss">
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: var(--fg-muted);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .label {
    line-height: 1;
  }
</style>
