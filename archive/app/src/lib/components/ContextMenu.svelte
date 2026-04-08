<!--
  ContextMenu.svelte — Generic positioned context menu overlay.
  Shows a list of actions at (x, y) and dismisses on click-outside or Escape.
-->
<script lang="ts">
  import { onMount } from 'svelte'

  export interface MenuItem {
    label?: string
    action?: () => void
    disabled?: boolean
    separator?: boolean
  }

  interface Props {
    x: number
    y: number
    items: MenuItem[]
    onclose: () => void
  }
  const { x, y, items, onclose }: Props = $props()

  let menuEl: HTMLElement | undefined = $state()

  onMount(() => {
    function handleDismiss(e: MouseEvent) {
      if (menuEl && !menuEl.contains(e.target as Node)) {
        onclose()
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onclose()
    }
    // Use a short timeout so the originating right-click doesn't immediately close the menu
    const timer = setTimeout(() => {
      window.addEventListener('mousedown', handleDismiss, true)
      window.addEventListener('contextmenu', handleDismiss, true)
      window.addEventListener('keydown', handleKeyDown)
    }, 50)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('mousedown', handleDismiss, true)
      window.removeEventListener('contextmenu', handleDismiss, true)
      window.removeEventListener('keydown', handleKeyDown)
    }
  })

  function handleItemClick(item: MenuItem) {
    if (item.separator || item.disabled || !item.action) return
    item.action()
    onclose()
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="context-menu"
  bind:this={menuEl}
  style="left: {x}px; top: {y}px"
>
  {#each items as item}
    {#if item.separator}
      <div class="menu-separator" aria-hidden="true"></div>
    {:else}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="menu-item"
        class:disabled={item.disabled}
        onclick={() => handleItemClick(item)}
      >
        {item.label}
      </div>
    {/if}
  {/each}
</div>

<style lang="postcss">
  .context-menu {
    position: fixed;
    z-index: 9999;
    min-width: 120px;
    background-color: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
    font-size: 12px;
  }

  .menu-item {
    padding: 4px 10px;
    cursor: pointer;
    color: var(--fg-primary);
    white-space: nowrap;
  }

  .menu-item:hover {
    background-color: var(--element-hover);
  }

  .menu-item.disabled {
    color: var(--fg-muted);
    cursor: default;
    opacity: 0.7;
  }

  .menu-item.disabled:hover {
    background-color: transparent;
  }

  .menu-separator {
    height: 1px;
    margin: 4px 6px;
    background-color: var(--border-variant);
  }
</style>
