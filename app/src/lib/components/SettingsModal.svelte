<!--
  SettingsModal.svelte
  Settings dialog opened from the title bar gear icon.
-->
<script lang="ts">
  import { theme } from '$stores/theme.svelte'
  import { backendClient } from '$services/backend-client'

  interface Props {
    onclose: () => void
  }

  const { onclose }: Props = $props()

  const promptKeys = ['prime_system', 'root_agent_system', 'sub_agent_system', 'tangle_maker', 'tangle_reviewer'] as const
  let prompts = $state<Record<string, { content: string; is_default: boolean; last_updated: string }>>({})
  let selectedPrompt = $state<string>('prime_system')
  let promptDraft = $state('')

  async function loadPrompts() {
    try {
      prompts = await backendClient.promptsList()
      const current = prompts[selectedPrompt]
      promptDraft = current?.content ?? ''
    } catch {
      // ignore
    }
  }

  function selectPrompt(key: string) {
    selectedPrompt = key
    promptDraft = prompts[key]?.content ?? ''
  }

  async function savePrompt() {
    try {
      const updated = await backendClient.promptsUpdate(selectedPrompt, promptDraft)
      prompts = { ...prompts, [selectedPrompt]: updated }
    } catch {
      // ignore
    }
  }

  async function resetPrompt() {
    try {
      const reset = await backendClient.promptsReset(selectedPrompt)
      prompts = { ...prompts, [selectedPrompt]: reset }
      promptDraft = reset.content
    } catch {
      // ignore
    }
  }

  loadPrompts()

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onclose()
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<svelte:window onkeydown={handleKeyDown} />
<div class="settings-backdrop" onclick={onclose}>
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="settings-modal"
    role="dialog"
    aria-label="Settings"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="settings-header">
      <h2 class="settings-title">Settings</h2>
      <button class="close-btn" onclick={onclose} aria-label="Close settings">✕</button>
    </div>

    <div class="settings-body">
      <!-- Theme -->
      <div class="setting-row">
        <div class="setting-info">
          <span class="setting-label">Theme</span>
          <span class="setting-desc">
            {theme.userOverride ? `Pinned: ${theme.isDark ? 'Dark' : 'Light'}` : `System (${theme.isDark ? 'Dark' : 'Light'})`}
          </span>
        </div>
        <div style="display:flex; gap:6px;">
          <button class="action-btn" onclick={() => theme.toggle()}>Toggle</button>
          {#if theme.userOverride}
            <button class="action-btn" onclick={() => theme.followSystem()}>Follow system</button>
          {/if}
        </div>
      </div>

      <!-- Placeholder for future settings -->
      <div class="setting-row">
        <div class="setting-info" style="width: 100%">
          <span class="setting-label">Prompts</span>
          <span class="setting-desc">Edit prime/root/sub/tangle prompts stored in project settings</span>
          <div class="prompt-controls">
            <select value={selectedPrompt} onchange={(e) => selectPrompt((e.currentTarget as HTMLSelectElement).value)}>
              {#each promptKeys as key}
                <option value={key}>{key}</option>
              {/each}
            </select>
            <button class="action-btn" onclick={savePrompt}>Save</button>
            <button class="action-btn" onclick={resetPrompt}>Reset</button>
          </div>
          <textarea
            class="prompt-editor"
            bind:value={promptDraft}
            rows="8"
            spellcheck="false"
          ></textarea>
        </div>
      </div>
    </div>
  </div>
</div>

<style lang="postcss">
  .settings-backdrop {
    position: fixed;
    inset: 0;
    z-index: 500;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 80px;
  }

  .settings-modal {
    width: 420px;
    max-width: calc(100vw - 32px);
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .settings-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }

  .settings-title {
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

  .settings-body {
    padding: 8px 0;
  }

  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
  }
  .setting-row.muted {
    opacity: 0.5;
  }

  .setting-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .setting-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--fg-primary);
  }

  .setting-desc {
    font-size: 11px;
    color: var(--fg-muted);
  }

  .prompt-controls {
    display: flex;
    gap: 8px;
    margin-top: 8px;
    margin-bottom: 8px;
  }

  .action-btn {
    border: 1px solid var(--border);
    background: var(--bg-base);
    color: var(--fg-primary);
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 12px;
  }

  .prompt-editor {
    width: 100%;
    background: var(--bg-base);
    color: var(--fg-primary);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-size: 12px;
    font-family: var(--font-mono, monospace);
    resize: vertical;
  }
</style>
