<!--
  FrontmatterProperties.svelte — YAML frontmatter property display.

  Shown at the top of the editor pane when a file has YAML frontmatter.
  Renders title, status, and last_updated as a clean horizontal bar.
-->
<script lang="ts">
  interface Props {
    frontmatter: Record<string, unknown>
    tabId?: string
  }
  const { frontmatter }: Props = $props()

  const title = $derived(frontmatter.title ? String(frontmatter.title) : null)
  const status = $derived(frontmatter.status ? String(frontmatter.status) : null)
  const lastUpdated = $derived(frontmatter.last_updated ? formatDateTime(String(frontmatter.last_updated)) : null)

  function statusClass(s: string): string {
    const v = s.toLowerCase()
    if (v === 'done' || v === 'complete' || v === 'verified') return 'status-done'
    if (v === 'in_progress' || v === 'in-progress' || v === 'active') return 'status-active'
    if (v === 'draft') return 'status-draft'
    if (v === 'blocked') return 'status-blocked'
    if (v === 'deprecated') return 'status-deprecated'
    return ''
  }

  function statusLabel(s: string): string {
    return s.replace(/_/g, ' ')
  }

  function formatDateTime(raw: string): string {
    // Try to parse as date/datetime
    const d = new Date(raw)
    if (isNaN(d.getTime())) return raw
    const hasTime = raw.includes('T') || raw.includes(' ')
    if (hasTime) {
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) +
        ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  }
</script>

{#if title || status || lastUpdated}
  <div class="frontmatter-bar">
    {#if status}
      <span class="status-badge {statusClass(status)}">
        <span class="status-dot"></span>
        {statusLabel(status)}
      </span>
    {/if}
    {#if lastUpdated}
      <span class="last-updated" title="Last updated">{lastUpdated}</span>
    {/if}
  </div>
{/if}

<style lang="postcss">
  .frontmatter-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 16px;
    border-bottom: 1px solid var(--border-variant);
    background-color: var(--bg-surface);
    flex-shrink: 0;
    font-size: 12px;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 500;
    text-transform: capitalize;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--element-bg);
    border: 1px solid var(--border-variant);
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--fg-muted);
  }

  .status-done .status-dot { background: var(--status-done); }
  .status-active .status-dot { background: var(--status-in-progress); }
  .status-draft .status-dot { background: var(--status-draft); }
  .status-blocked .status-dot { background: var(--status-blocked); }
  .status-deprecated .status-dot { background: var(--fg-muted); }

  .status-done { color: var(--status-done); border-color: var(--status-done); }
  .status-active { color: var(--status-in-progress); border-color: var(--status-in-progress); }
  .status-draft { color: var(--status-draft); border-color: var(--status-draft); }
  .status-blocked { color: var(--status-blocked); border-color: var(--status-blocked); }
  .status-deprecated { color: var(--fg-muted); border-color: var(--fg-muted); }

  .last-updated {
    color: var(--fg-muted);
    font-size: 11px;
    margin-left: auto;
  }
</style>
