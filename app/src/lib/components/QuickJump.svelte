<!--
  8.3 QuickJump.svelte
  Cmd+P modal: fuzzy finder that navigates to a spec_ref by selecting a node.
  Searches node labels and spec_refs.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'

  interface Props {
    onclose: () => void
  }
  const { onclose }: Props = $props()

  let query = $state('')
  let selectedIndex = $state(0)
  let inputEl: HTMLInputElement | undefined = $state()

  // All spec nodes from the flat tree (includes collapsed children)
  const allNodes = $derived(
    appState.nodes
      .map((n, id) => ({ id, label: n.markdown.split('\n')[0].trim() || '…', specRef: n.specRef, depth: 0 }))
      .filter((n) => n.specRef)
  )

  const filtered = $derived(
    query.trim() === ''
      ? allNodes.slice(0, 50)
      : allNodes.filter((n) => {
          const q = query.toLowerCase()
          return n.label.toLowerCase().includes(q) || n.specRef.toLowerCase().includes(q)
        }).slice(0, 50)
  )

  $effect(() => {
    void filtered.length
    selectedIndex = 0
  })

  $effect(() => {
    tick().then(() => inputEl?.focus())
  })

  function jump(nodeId: number) {
    dispatch({ type: 'selectNode', nodeId })
    onclose()
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault(); onclose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault(); selectedIndex = Math.min(selectedIndex + 1, filtered.length - 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); selectedIndex = Math.max(selectedIndex - 1, 0)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = filtered[selectedIndex]
      if (item) jump(item.id)
    }
  }

  // Highlight matching substring
  function highlight(text: string, q: string): string {
    if (!q) return text
    const idx = text.toLowerCase().indexOf(q.toLowerCase())
    if (idx === -1) return text
    return (
      text.slice(0, idx) +
      '<mark>' +
      text.slice(idx, idx + q.length) +
      '</mark>' +
      text.slice(idx + q.length)
    )
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="jump-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="jump-modal"
    role="dialog"
    aria-label="Quick jump"
    onclick={(e) => e.stopPropagation()}
    onkeydown={handleKeyDown}
  >
    <div class="jump-search">
      <span class="search-icon">⌘P</span>
      <input
        bind:this={inputEl}
        bind:value={query}
        class="search-input"
        type="text"
        placeholder="Jump to spec node…"
        autocomplete="off"
        spellcheck="false"
        aria-label="Node search"
      />
    </div>

    <ul class="jump-list" role="listbox">
      {#each filtered as item, i (item.id)}
        <!-- svelte-ignore a11y_interactive_supports_focus -->
        <li
          class="jump-item"
          class:active={i === selectedIndex}
          role="option"
          aria-selected={i === selectedIndex}
          onmouseenter={() => { selectedIndex = i }}
          onclick={() => jump(item.id)}
        >
          <span class="node-label">{@html highlight(item.label, query)}</span>
          <span class="spec-ref">{@html highlight(item.specRef, query)}</span>
        </li>
      {/each}
      {#if filtered.length === 0}
        <li class="jump-empty">No matching nodes</li>
      {/if}
    </ul>

    <div class="jump-footer">
      <span>↑↓ navigate</span>
      <span>↵ jump</span>
      <span>Esc close</span>
    </div>
  </div>
</div>

<style lang="postcss">
  .jump-backdrop {
    position: fixed;
    inset: 0;
    z-index: 500;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 80px;
  }

  .jump-modal {
    width: 520px;
    max-width: calc(100vw - 32px);
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    max-height: 420px;
  }

  .jump-search {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .search-icon {
    color: var(--fg-muted);
    font-size: 11px;
    font-family: var(--font-mono);
    flex-shrink: 0;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
    white-space: nowrap;
  }

  .search-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--fg-primary);
    font-size: 14px;
    caret-color: var(--fg-accent);
  }
  .search-input::placeholder { color: var(--fg-muted); }

  .jump-list {
    list-style: none;
    margin: 0;
    padding: 4px 0;
    overflow-y: auto;
    flex: 1;
  }

  .jump-item {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 6px 14px;
    cursor: pointer;
    transition: background-color 0.1s;
  }
  .jump-item.active { background-color: var(--element-selected); }
  .jump-item:hover { background-color: var(--element-hover); }

  .node-label {
    font-size: 13px;
    color: var(--fg-primary);
    flex-shrink: 0;
    max-width: 55%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .spec-ref {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  :global(mark) {
    background: color-mix(in srgb, var(--fg-accent) 30%, transparent);
    color: inherit;
    border-radius: 2px;
  }

  .jump-empty {
    padding: 12px 14px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
    list-style: none;
  }

  .jump-footer {
    display: flex;
    gap: 16px;
    padding: 6px 14px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    font-size: 10px;
    color: var(--fg-muted);
  }
</style>
