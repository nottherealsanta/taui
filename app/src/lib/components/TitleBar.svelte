<!--
  4.1 TitleBar.svelte
  Custom draggable titlebar with Tauri window controls.
-->
<script lang="ts">
  import { appState } from '$stores/app-state.svelte'
  import { theme } from '$stores/theme.svelte'

  const connected = $derived(appState.connectionState === 'ready')
  const title = $derived(appState.rootTitle)
</script>

<header class="titlebar" data-tauri-drag-region>
  <!-- Left: title -->
  <div class="titlebar-left" data-tauri-drag-region>
    <span class="titlebar-title">{title}</span>
  </div>

  <!-- Center: connection status -->
  <div class="titlebar-center" data-tauri-drag-region>
    <span class="status-dot" class:connected></span>
    <span class="status-label">
      {#if appState.connectionState === 'ready'}connected
      {:else if appState.connectionState === 'connecting'}connecting…
      {:else if typeof appState.connectionState === 'object'}error
      {:else}offline{/if}
    </span>
  </div>

  <!-- Right: theme toggle + window controls -->
  <div class="titlebar-right">
    <button class="ctrl theme-btn" onclick={() => theme.toggle()} title="Toggle theme" aria-label="Toggle theme">
      {theme.isDark ? '☀' : '☾'}
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
    display: flex;
    align-items: center;
    padding-left: 78px; /* space for macOS traffic lights under overlay titlebar */
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

  .titlebar-center {
    display: flex;
    align-items: center;
    gap: 5px;
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
  }

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: var(--status-blocked);
    flex-shrink: 0;
    transition: background-color 0.25s ease;
  }
  .status-dot.connected { background-color: var(--status-done); }

  .status-label {
    font-size: 11px;
    color: var(--fg-muted);
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
  .theme-btn { font-size: 13px; }
  .close-btn:hover { background-color: var(--status-blocked); color: #fff; }
</style>
