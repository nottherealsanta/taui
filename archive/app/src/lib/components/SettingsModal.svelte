<!--
  SettingsModal.svelte
  Settings dialog opened from the title bar gear icon.
-->
<script lang="ts">
  import { theme } from '$stores/theme.svelte'

  interface Props {
    onclose: () => void
  }

  const { onclose }: Props = $props()

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onclose()
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="settings-backdrop" onclick={onclose} onkeydown={handleKeyDown}>
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
          <span class="setting-desc">Current: {theme.isDark ? 'Dark' : 'Light'} (follows system)</span>
        </div>
      </div>

      <!-- Placeholder for future settings -->
      <div class="setting-row muted">
        <span class="setting-label">More settings coming soon…</span>
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
</style>
