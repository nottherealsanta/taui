<script lang="ts">
  import Self from '$components/SpecNavItem.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import type { SpecNavHeadingItem, SpecNavItemType } from '$types/spec-nav'

  interface Props {
    item: SpecNavItemType
    depth?: number
    collapsedKeys: Set<string>
    activeFilePath: string | null
    selectedFilePath: string | null
    ontoggle: (key: string) => void
    onselect: (item: SpecNavHeadingItem) => void
  }

  const {
    item,
    depth = 0,
    collapsedKeys,
    activeFilePath,
    selectedFilePath,
    ontoggle,
    onselect,
  }: Props = $props()

  const isCollapsed = $derived(collapsedKeys.has(item.key))
  const isActive = $derived(
    item.kind === 'heading' && (
      item.filePath === selectedFilePath ||
      item.filePath === activeFilePath
    )
  )

  function toggleItem(e: MouseEvent) {
    e.stopPropagation()
    ontoggle(item.key)
  }

  async function selectItem() {
    if (item.kind !== 'heading') return

    appState.setSelected(item.nodeId)
    appState.editorMode = 'normal'
    await tabStore.openFile(item.filePath)
    onselect(item)
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="nav-item" style:padding-left="{10 + depth * 16}px">
  {#if item.kind === 'folder'}
    <div class="nav-row folder" onclick={item.children.length > 0 ? toggleItem : undefined}>
      <span class="chevron">{item.children.length > 0 ? (isCollapsed ? '▸' : '▾') : '·'}</span>
      <span class="label">{item.label}</span>
    </div>
    {#if !isCollapsed}
      {#each item.children as child (child.key)}
        <Self
          item={child}
          depth={depth + 1}
          {collapsedKeys}
          {activeFilePath}
          {selectedFilePath}
          {ontoggle}
          {onselect}
        />
      {/each}
    {/if}
  {:else}
    <div class="nav-row heading" class:active={isActive} onclick={selectItem}>
      {#if item.collapsible}
        <button class="chevron-btn" onclick={toggleItem} aria-label={isCollapsed ? 'Expand section' : 'Collapse section'}>
          {isCollapsed ? '▸' : '▾'}
        </button>
      {:else}
        <span class="chevron spacer">·</span>
      {/if}
      <span class="label">{item.label}</span>
    </div>
    {#if item.children.length > 0 && !isCollapsed}
      {#each item.children as child (child.key)}
        <Self
          item={child}
          depth={depth + 1}
          {collapsedKeys}
          {activeFilePath}
          {selectedFilePath}
          {ontoggle}
          {onselect}
        />
      {/each}
    {/if}
  {/if}
</div>

<style lang="postcss">
  .nav-item {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .nav-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 26px;
    border-radius: 4px;
    padding: 2px 8px 2px 0;
    color: var(--fg-primary);
    min-width: 0;
  }

  .nav-row.folder {
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
    text-transform: none;
    letter-spacing: 0.01em;
  }

  .nav-row.heading {
    cursor: pointer;
    font-size: 13px;
  }

  .nav-row:hover {
    background-color: var(--element-hover);
  }

  .nav-row.active {
    background-color: var(--element-selected);
    color: var(--fg-primary);
  }

  .chevron,
  .chevron-btn {
    width: 14px;
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--fg-muted);
    font-size: 10px;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
  }

  .chevron-btn {
    cursor: pointer;
    border-radius: 3px;
  }

  .chevron-btn:hover {
    background-color: var(--element-bg);
    color: var(--fg-primary);
  }

  .spacer {
    opacity: 0.35;
  }

  .label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>