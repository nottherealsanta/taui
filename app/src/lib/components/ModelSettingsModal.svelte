<!--
  ModelSettingsModal.svelte
  Modal for configuring which model is assigned to each L/M/H mode.
  Each mode has primary, secondary (fallback), and tertiary (fallback) slots.
-->
<script lang="ts">
  import type { ModelModeKey, ModelModeConfig, ModelSlot } from '$types/index'
  import { appState } from '$stores/app-state.svelte'

  interface Props {
    onclose: () => void
  }

  const { onclose }: Props = $props()

  const MODES: { key: ModelModeKey; label: string; shortLabel: string }[] = [
    { key: 'low', label: 'Low', shortLabel: 'L' },
    { key: 'medium', label: 'Medium', shortLabel: 'M' },
    { key: 'high', label: 'High', shortLabel: 'H' },
  ]

  const ALL_MODELS: { provider: string; model: string }[] = [
    { provider: 'copilot', model: 'claude-haiku-4.5' },
    { provider: 'copilot', model: 'claude-sonnet-4.6' },
    { provider: 'copilot', model: 'claude-opus-4.6' },
    { provider: 'copilot', model: 'gpt-5.3-codex' },
    { provider: 'copilot', model: 'gemini-3.1-pro-preview' },
  ]

  let activeTab: ModelModeKey = $state(appState.activeModelMode)
  let search = $state('')

  // Deep-clone the current config to work on locally
  let localModes: Record<ModelModeKey, ModelModeConfig> = $state(
    JSON.parse(JSON.stringify(appState.modelModes))
  )

  const filteredModels = $derived(() => {
    const q = search.toLowerCase().trim()
    if (!q) return ALL_MODELS
    return ALL_MODELS.filter(
      (m) => m.model.toLowerCase().includes(q) || m.provider.toLowerCase().includes(q),
    )
  })

  const currentConfig = $derived(() => localModes[activeTab])

  type SlotKey = 'primary' | 'secondary' | 'tertiary'
  let activeSlot: SlotKey = $state('primary')

  function selectModel(provider: string, model: string) {
    const slot: ModelSlot = { provider, model }
    const cfg = { ...localModes[activeTab] }

    if (activeSlot === 'primary') {
      cfg.primary = slot
    } else if (activeSlot === 'secondary') {
      cfg.secondary = slot
    } else {
      cfg.tertiary = slot
    }

    localModes = { ...localModes, [activeTab]: cfg }
  }

  function clearSlot(slotKey: SlotKey) {
    if (slotKey === 'primary') return // Can't clear primary
    const cfg = { ...localModes[activeTab] }
    if (slotKey === 'secondary') cfg.secondary = null
    if (slotKey === 'tertiary') cfg.tertiary = null
    localModes = { ...localModes, [activeTab]: cfg }
  }

  function slotDisplay(slot: ModelSlot | null): string {
    if (!slot) return 'None'
    return slot.model
  }

  function isSelected(provider: string, model: string): boolean {
    const cfg = currentConfig()
    const slot = cfg[activeSlot]
    return slot !== null && slot.provider === provider && slot.model === model
  }

  function save() {
    for (const mode of MODES) {
      appState.setModelModeConfig(mode.key, localModes[mode.key])
    }
    onclose()
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onclose()
    }
  }

  let searchEl: HTMLInputElement | undefined = $state()

  $effect(() => {
    // Auto-focus search on open
    searchEl?.focus()
  })
</script>

<svelte:window onkeydown={handleKeyDown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="modal-panel"
    role="dialog"
    aria-label="Model Settings"
    onclick={(e) => e.stopPropagation()}
  >
    <!-- Header -->
    <div class="modal-header">
      <h2 class="modal-title">Model Settings</h2>
      <button class="close-btn" onclick={onclose} aria-label="Close">✕</button>
    </div>

    <!-- Mode tabs -->
    <div class="mode-tabs">
      {#each MODES as mode}
        <button
          class="mode-tab"
          class:active={activeTab === mode.key}
          onclick={() => { activeTab = mode.key; activeSlot = 'primary' }}
        >
          <span class="mode-tab-short">{mode.shortLabel}</span>
          <span class="mode-tab-label">{mode.label}</span>
        </button>
      {/each}
    </div>

    <!-- Slot selector -->
    <div class="slot-section">
      <div class="slot-tabs">
        {#each [['primary', 'Primary'] as const, ['secondary', 'Fallback'] as const, ['tertiary', 'Fallback 2'] as const] as [key, label]}
          <button
            class="slot-tab"
            class:active={activeSlot === key}
            onclick={() => { activeSlot = key }}
          >
            <span class="slot-label">{label}</span>
            <span class="slot-model">{slotDisplay(currentConfig()[key])}</span>
          </button>
        {/each}
      </div>

      {#if activeSlot !== 'primary' && currentConfig()[activeSlot]}
        <button class="clear-slot-btn" onclick={() => clearSlot(activeSlot)}>
          Clear {activeSlot === 'secondary' ? 'fallback' : 'fallback 2'}
        </button>
      {/if}
    </div>

    <!-- Search -->
    <div class="search-row">
      <input
        bind:this={searchEl}
        bind:value={search}
        class="search-input"
        type="text"
        placeholder="Search models…"
        autocomplete="off"
        spellcheck="false"
      />
    </div>

    <!-- Model list -->
    <div class="model-list">
      {#each filteredModels() as m (m.provider + ':' + m.model)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="model-item"
          class:selected={isSelected(m.provider, m.model)}
          onclick={() => selectModel(m.provider, m.model)}
        >
          <span class="model-name">{m.model}</span>
          <span class="model-provider">{m.provider}</span>
        </div>
      {/each}
      {#if filteredModels().length === 0}
        <div class="model-empty">No models match "{search}"</div>
      {/if}
    </div>

    <!-- Footer -->
    <div class="modal-footer">
      <button class="footer-btn cancel-btn" onclick={onclose}>Cancel</button>
      <button class="footer-btn save-btn" onclick={save}>Save</button>
    </div>
  </div>
</div>

<style lang="postcss">
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 500;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 60px;
  }

  .modal-panel {
    width: 440px;
    max-width: calc(100vw - 32px);
    max-height: calc(100vh - 120px);
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .modal-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--fg-primary);
    margin: 0;
  }

  .close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    font-size: 12px;
    cursor: pointer;
    border-radius: 4px;
    transition: background-color 0.15s, color 0.15s;
  }
  .close-btn:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  /* ── Mode tabs (L / M / H) ─────────────────────────────────────────────── */

  .mode-tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .mode-tab {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 10px 8px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .mode-tab:hover {
    color: var(--fg-primary);
    background: var(--element-hover);
  }
  .mode-tab.active {
    color: var(--fg-accent);
    border-bottom-color: var(--fg-accent);
  }

  .mode-tab-short {
    font-weight: 700;
    font-size: 13px;
    font-family: var(--font-mono);
  }

  .mode-tab-label {
    font-size: 11px;
    opacity: 0.8;
  }

  /* ── Slot selector ──────────────────────────────────────────────────────── */

  .slot-section {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .slot-tabs {
    display: flex;
    gap: 4px;
  }

  .slot-tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: transparent;
    cursor: pointer;
    transition: all 0.15s;
  }
  .slot-tab:hover {
    background: var(--element-hover);
  }
  .slot-tab.active {
    border-color: var(--fg-accent);
    background: color-mix(in srgb, var(--fg-accent) 8%, transparent);
  }

  .slot-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-muted);
  }

  .slot-model {
    font-size: 11px;
    color: var(--fg-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }

  .clear-slot-btn {
    margin-top: 6px;
    padding: 3px 8px;
    font-size: 10px;
    color: var(--fg-muted);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .clear-slot-btn:hover {
    color: var(--fg-primary);
    border-color: var(--fg-primary);
  }

  /* ── Search ─────────────────────────────────────────────────────────────── */

  .search-row {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .search-input {
    width: 100%;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--bg-base);
    color: var(--fg-primary);
    font-size: 13px;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color 0.15s;
  }
  .search-input:focus {
    border-color: var(--fg-accent);
  }
  .search-input::placeholder {
    color: var(--fg-muted);
  }

  /* ── Model list ─────────────────────────────────────────────────────────── */

  .model-list {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
    min-height: 120px;
    max-height: 240px;
  }

  .model-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    cursor: pointer;
    transition: background-color 0.1s;
  }
  .model-item:hover {
    background-color: var(--element-hover);
  }
  .model-item.selected {
    background-color: color-mix(in srgb, var(--fg-accent) 12%, transparent);
  }

  .model-name {
    font-size: 13px;
    font-weight: 500;
    color: var(--fg-primary);
    font-family: var(--font-mono);
  }
  .model-item.selected .model-name {
    color: var(--fg-accent);
  }

  .model-provider {
    font-size: 11px;
    color: var(--fg-muted);
  }

  .model-empty {
    padding: 20px 16px;
    text-align: center;
    font-size: 12px;
    color: var(--fg-muted);
  }

  /* ── Footer ─────────────────────────────────────────────────────────────── */

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 10px 16px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }

  .footer-btn {
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 500;
    border-radius: 5px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .cancel-btn {
    border: 1px solid var(--border);
    background: transparent;
    color: var(--fg-muted);
  }
  .cancel-btn:hover {
    color: var(--fg-primary);
    border-color: var(--fg-primary);
  }

  .save-btn {
    border: 1px solid var(--fg-accent);
    background: var(--fg-accent);
    color: var(--bg-base);
  }
  .save-btn:hover {
    opacity: 0.9;
  }
</style>
