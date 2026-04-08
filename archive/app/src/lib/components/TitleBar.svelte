<!--
  4.1 TitleBar.svelte
  Custom draggable titlebar with Tauri window controls.
-->
<script lang="ts">
  import { appState } from '$stores/app-state.svelte'

  const title = $derived(appState.rootTitle)
</script>

<header class="titlebar" data-tauri-drag-region>
  <!-- Left: spacer for macOS traffic lights -->
  <div class="titlebar-left" data-tauri-drag-region></div>

  <!-- Center: project name -->
  <div class="titlebar-center" data-tauri-drag-region>
    <span class="titlebar-title">{title}</span>
  </div>

  <!-- Right: settings -->
  <div class="titlebar-right">
    <button class="ctrl settings-btn" onclick={() => window.dispatchEvent(new CustomEvent('taui:toggle-settings'))} title="Settings" aria-label="Settings">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
  </div>
</header>

<style lang="postcss">
  .titlebar {
    display: flex;
    align-items: center;
    height: 36px;
    background-color: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    -webkit-app-region: drag;
    app-region: drag;
    user-select: none;
    position: relative;
    z-index: 100;
  }

  .titlebar-left {
    flex: 1;
    padding-left: 78px; /* space for macOS traffic lights under overlay titlebar */
  }

  .titlebar-center {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
  }

  .titlebar-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg-primary);
    letter-spacing: 0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .titlebar-right {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 2px;
    padding-right: 4px;
    -webkit-app-region: no-drag;
    app-region: no-drag;
  }

  .ctrl {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    font-size: 12px;
    cursor: pointer;
    border-radius: 4px;
    transition: background-color 0.15s, color 0.15s;
  }
  .ctrl:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }
  .settings-btn { font-size: 14px; }
</style>
