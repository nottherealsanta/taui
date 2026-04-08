<!--
  8.2 CommandPalette.svelte
  Cmd+Shift+P modal: fuzzy search over available actions.
  Closes on Escape or clicking outside.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'
  import { theme } from '$stores/theme.svelte'
  import { fileTree } from '$stores/file-tree.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { backendClient } from '$services/backend-client'

  interface Props {
    onclose: () => void
  }
  const { onclose }: Props = $props()

  interface PaletteAction {
    label: string
    description?: string
    run: () => void
  }

  const actions: PaletteAction[] = [
    {
      label: 'Toggle theme',
      description: 'Switch between dark and light',
      run: () => theme.toggle(),
    },
    {
      label: 'Select next node',
      description: '↓ Move selection down',
      run: () => dispatch({ type: 'selectNext' }),
    },
    {
      label: 'Select previous node',
      description: '↑ Move selection up',
      run: () => dispatch({ type: 'selectPrevious' }),
    },
    {
      label: 'Enter editing mode',
      description: 'Edit the selected node inline',
      run: () => { if (appState.selectedNode !== null) dispatch({ type: 'enterEditing' }) },
    },
    {
      label: 'Exit editing mode',
      description: 'Return to tree navigation',
      run: () => dispatch({ type: 'exitEditing' }),
    },
    {
      label: 'Add sibling node',
      description: 'Create a new node below selected',
      run: () => dispatch({ type: 'addSiblingNode' }),
    },
    {
      label: 'Indent node (Tab)',
      description: 'Make selected node a child',
      run: () => {
        const ref = appState.selectedSpecRef
        dispatch({ type: 'indentNode' })
        if (ref) backendClient.indentNode(ref).catch(console.error)
      },
    },
    {
      label: 'Outdent node (Shift+Tab)',
      description: 'Promote selected node to parent level',
      run: () => {
        const ref = appState.selectedSpecRef
        dispatch({ type: 'outdentNode' })
        if (ref) backendClient.outdentNode(ref).catch(console.error)
      },
    },
    {
      label: 'Collapse / expand node',
      description: 'Toggle collapse of selected node',
      run: () => dispatch({ type: 'toggleCollapse' }),
    },
    {
      label: 'Launch agent (low)',
      description: 'Launch a low-tier agent on selected node',
      run: () => { appState.launchTier = 'low' },
    },
    {
      label: 'Launch agent (medium)',
      description: 'Launch a medium-tier agent on selected node',
      run: () => { appState.launchTier = 'medium' },
    },
    {
      label: 'Launch agent (high)',
      description: 'Launch a high-tier agent on selected node',
      run: () => { appState.launchTier = 'high' },
    },
    {
      label: 'Toggle left sidebar',
      description: 'Show/hide the file tree sidebar (Cmd+B)',
      run: () => { fileTree.toggleSidebar() },
    },
    {
      label: 'Toggle right sidebar',
      description: 'Show/hide the right panel (Cmd+Shift+B)',
      run: () => { window.dispatchEvent(new CustomEvent('taui:toggle-right-sidebar')) },
    },
    {
      label: 'Search in files',
      description: 'Open global file search (Cmd+Shift+F)',
      run: () => { window.dispatchEvent(new CustomEvent('taui:toggle-search')) },
    },
    {
      label: 'Open graph view',
      description: 'Show link graph visualization (Cmd+Shift+G)',
      run: () => { window.dispatchEvent(new CustomEvent('taui:toggle-graph')) },
    },
    {
      label: 'Close current tab',
      description: 'Close the active editor tab',
      run: () => { if (tabStore.activeTabId) void tabStore.closeTab(tabStore.activeTabId) },
    },
    {
      label: 'Close all tabs',
      description: 'Close all open editor tabs',
      run: () => { void tabStore.closeAllTabs() },
    },
    {
      label: 'Save current file',
      description: 'Save the active file (Cmd+S)',
      run: () => { tabStore.save() },
    },
  ]

  let query = $state('')
  let selectedIndex = $state(0)
  let inputEl: HTMLInputElement | undefined = $state()

  const filtered = $derived(
    query.trim() === ''
      ? actions
      : actions.filter((a) => {
          const q = query.toLowerCase()
          return (
            a.label.toLowerCase().includes(q) ||
            (a.description?.toLowerCase().includes(q) ?? false)
          )
        })
  )

  // Reset selection when filter changes
  $effect(() => {
    void filtered.length
    selectedIndex = 0
  })

  // Auto-focus input on open
  $effect(() => {
    tick().then(() => inputEl?.focus())
  })

  function run(action: PaletteAction) {
    action.run()
    onclose()
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onclose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      selectedIndex = Math.min(selectedIndex + 1, filtered.length - 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      selectedIndex = Math.max(selectedIndex - 1, 0)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const action = filtered[selectedIndex]
      if (action) run(action)
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="palette-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="palette-modal"
    role="dialog"
    aria-label="Command palette"
    onclick={(e) => e.stopPropagation()}
    onkeydown={handleKeyDown}
  >
    <div class="palette-search">
      <span class="search-icon">⌘</span>
      <input
        bind:this={inputEl}
        bind:value={query}
        class="search-input"
        type="text"
        placeholder="Type a command…"
        autocomplete="off"
        spellcheck="false"
        aria-label="Command search"
      />
    </div>

    <ul class="palette-list" role="listbox" aria-label="Actions">
      {#each filtered as action, i (action.label)}
        <!-- svelte-ignore a11y_interactive_supports_focus -->
        <li
          class="palette-item"
          class:active={i === selectedIndex}
          role="option"
          aria-selected={i === selectedIndex}
          onmouseenter={() => { selectedIndex = i }}
          onclick={() => run(action)}
        >
          <span class="action-label">{action.label}</span>
          {#if action.description}
            <span class="action-desc">{action.description}</span>
          {/if}
        </li>
      {/each}
      {#if filtered.length === 0}
        <li class="palette-empty">No matching commands</li>
      {/if}
    </ul>

    <div class="palette-footer">
      <span>↑↓ navigate</span>
      <span>↵ run</span>
      <span>Esc close</span>
    </div>
  </div>
</div>

<style lang="postcss">
  .palette-backdrop {
    position: fixed;
    inset: 0;
    z-index: 500;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 80px;
  }

  .palette-modal {
    width: 480px;
    max-width: calc(100vw - 32px);
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    max-height: 400px;
  }

  .palette-search {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .search-icon {
    color: var(--fg-muted);
    font-size: 14px;
    flex-shrink: 0;
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

  .palette-list {
    list-style: none;
    margin: 0;
    padding: 4px 0;
    overflow-y: auto;
    flex: 1;
  }

  .palette-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 14px;
    cursor: pointer;
    transition: background-color 0.1s;
  }
  .palette-item.active { background-color: var(--element-selected); }
  .palette-item:hover { background-color: var(--element-hover); }

  .action-label {
    font-size: 13px;
    color: var(--fg-primary);
    flex-shrink: 0;
  }

  .action-desc {
    font-size: 11px;
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .palette-empty {
    padding: 12px 14px;
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
    list-style: none;
  }

  .palette-footer {
    display: flex;
    gap: 16px;
    padding: 6px 14px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    font-size: 10px;
    color: var(--fg-muted);
  }
</style>
