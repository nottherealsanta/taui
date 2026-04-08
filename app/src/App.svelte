<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { startConnection, stopConnection } from '$services/connection'
  import { appState } from '$stores/app-state.svelte'
  import { fileTree } from '$stores/file-tree.svelte'
  import { tabStore } from '$stores/tabs.svelte'
  import { theme } from '$stores/theme.svelte'
  import TitleBar from '$components/TitleBar.svelte'
  import SplitPane from '$components/SplitPane.svelte'
  import TangleNavSidebar from '$components/TangleNavSidebar.svelte'
  import MainPane from '$components/MainPane.svelte'
  import SearchPanel from '$components/SearchPanel.svelte'
  import GraphView from '$components/GraphView.svelte'
  import BottomDrawer from '$components/BottomDrawer.svelte'
  import CommandPalette from '$components/CommandPalette.svelte'
  import QuickJump from '$components/QuickJump.svelte'
  import Toast from '$components/Toast.svelte'
  import SettingsModal from '$components/SettingsModal.svelte'

  onMount(() => {
    startConnection()
    listenMenuEvents()

    // Listen for custom events from CommandPalette
    window.addEventListener('taui:toggle-search', handleToggleSearch)
    window.addEventListener('taui:toggle-graph', handleToggleGraph)
    window.addEventListener('taui:toggle-right-sidebar', handleToggleRightSidebar)
    window.addEventListener('taui:toggle-settings', handleToggleSettings)
  })
  onDestroy(() => {
    stopConnection()
    window.removeEventListener('taui:toggle-search', handleToggleSearch)
    window.removeEventListener('taui:toggle-graph', handleToggleGraph)
    window.removeEventListener('taui:toggle-right-sidebar', handleToggleRightSidebar)
    window.removeEventListener('taui:toggle-settings', handleToggleSettings)
  })

  function handleToggleSearch() { showSearch = !showSearch }
  function handleToggleGraph() { showGraph = !showGraph }
  function handleToggleRightSidebar() { toggleRightSidebar() }
  function handleToggleSettings() { showSettings = !showSettings }

  async function listenMenuEvents() {
    try {
      const { listen } = await import('@tauri-apps/api/event')
      await listen('menu://toggle_theme', () => { theme.toggle() })
      await listen('menu://command_palette', () => { showPalette = true; showJump = false })
      await listen('menu://quick_jump', () => { showJump = true; showPalette = false })
    } catch {
      // Not running inside Tauri (e.g. browser dev mode) — ignore
    }
  }

  // ── Bottom drawer state ────────────────────────────────────────────────────
  let drawerOpen = $state(false)

  // ── Agent pane state ──────────────────────────────────────────────────────
  let rightSidebarCollapsed = $state(false)

  function toggleRightSidebar() {
    rightSidebarCollapsed = !rightSidebarCollapsed
  }

  // ── Search panel state ────────────────────────────────────────────────────
  let showSearch = $state(false)

  // ── Graph view state ──────────────────────────────────────────────────────
  let showGraph = $state(false)

  // ── Modals ─────────────────────────────────────────────────────────────────
  let showPalette = $state(false)
  let showJump = $state(false)
  let showSettings = $state(false)

  // ── Global keybindings ─────────────────────────────────────────────────────
  function handleGlobalKeyDown(e: KeyboardEvent) {
    const meta = e.metaKey || e.ctrlKey
    if (!meta) return

    const tag = (e.target as HTMLElement)?.tagName
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA'

    if (e.key === 'p' && !e.shiftKey) {
      // Cmd+P → Quick Jump
      if (isInput) return
      e.preventDefault()
      showJump = !showJump
      showPalette = false
    } else if (e.key === 'P' || (e.key === 'p' && e.shiftKey)) {
      // Cmd+Shift+P → Command Palette
      if (isInput) return
      e.preventDefault()
      showPalette = !showPalette
      showJump = false
    } else if (e.key === 'f' && e.shiftKey) {
      // Cmd+Shift+F → Search in files
      e.preventDefault()
      showSearch = !showSearch
    } else if (e.key === 'g' && e.shiftKey) {
      // Cmd+Shift+G → Graph view
      e.preventDefault()
      showGraph = !showGraph
    } else if (e.key === 's') {
      // Cmd+S → Save current tab
      e.preventDefault()
      tabStore.save()
    } else if (e.key === 'b' && !e.shiftKey) {
      // Cmd+B → Toggle left sidebar
      if (isInput) return
      e.preventDefault()
      fileTree.toggleSidebar()
    } else if (e.key === 'B' || (e.key === 'b' && e.shiftKey)) {
      // Cmd+Shift+B → Toggle right sidebar
      if (isInput) return
      e.preventDefault()
      toggleRightSidebar()
    } else if (e.key === 'w') {
      // Cmd+W → Close current tab
      e.preventDefault()
      if (tabStore.activeTabId) void tabStore.closeTab(tabStore.activeTabId)
    }
  }

  // ── Dynamic window title ───────────────────────────────────────────────────
  $effect(() => {
    const title = appState.rootTitle
    const status = appState.connectionState === 'ready' ? '' : ' — offline'
    document.title = `${title}${status}`
  })
</script>

<div class="app-shell">
  <TitleBar />

  <div class="app-body">
    {#if appState.connectionState === 'offline' || appState.connectionState === 'connecting'}
      <div class="connection-screen">
        <div class="conn-icon">⚡</div>
        <p class="conn-status">
          {appState.connectionState === 'connecting' ? 'Connecting to backend…' : 'Waiting for backend'}
        </p>
        <p class="conn-hint">Start with <code>uv run taui</code></p>
      </div>
    {:else if typeof appState.connectionState === 'object' && 'error' in appState.connectionState}
      <div class="connection-screen error">
        <div class="conn-icon">✗</div>
        <p class="conn-status">Connection error</p>
        <p class="conn-hint">{appState.connectionState.error}</p>
      </div>
    {:else}
      <!-- Three-column Obsidian-like layout -->
      <SplitPane
        direction="horizontal"
        initialSize={250}
        minSize={150}
        maxSize={500}
        storageKey="taui-left-sidebar-width"
        collapsed={fileTree.sidebarCollapsed}
      >
        {#snippet first()}
          {#if showSearch}
            <SearchPanel onclose={() => { showSearch = false }} />
          {:else}
            <TangleNavSidebar />
          {/if}
        {/snippet}

        {#snippet second()}
          <MainPane agentPaneCollapsed={rightSidebarCollapsed} />
        {/snippet}
      </SplitPane>
    {/if}
  </div>

  <!-- Graph view overlay -->
  {#if showGraph}
    <div class="graph-overlay">
      <GraphView onclose={() => { showGraph = false }} />
    </div>
  {/if}

  <!-- Bottom drawer (Code + Terminal) -->
  {#if drawerOpen}
    <BottomDrawer
      onclose={() => { drawerOpen = false }}
    />
  {/if}
</div>

<!-- Modals (outside app-shell to avoid stacking context issues) -->
{#if showPalette}
  <CommandPalette onclose={() => { showPalette = false }} />
{/if}
{#if showJump}
  <QuickJump onclose={() => { showJump = false }} />
{/if}
{#if showSettings}
  <SettingsModal onclose={() => { showSettings = false }} />
{/if}

<!-- Toast notifications -->
<Toast />

<svelte:window onkeydown={handleGlobalKeyDown} />

<style lang="postcss">
  .app-shell {
    display: flex;
    flex-direction: column;
    height: 100%;
    background-color: var(--bg-base);
    color: var(--fg-primary);
    overflow: hidden;
  }

  .app-body {
    flex: 1;
    display: flex;
    min-height: 0;
    overflow: hidden;
  }

  /* ── Connection / error screens ─────────────────────────────────── */
  .connection-screen {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: var(--fg-muted);
    padding: 40px;
    text-align: center;
  }

  .conn-icon {
    font-size: 40px;
    line-height: 1;
    margin-bottom: 4px;
  }

  .conn-status {
    margin: 0;
    font-size: 15px;
    color: var(--fg-primary);
  }

  .conn-hint {
    margin: 0;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .conn-hint code {
    font-family: var(--font-mono);
    color: var(--fg-accent);
  }

  .connection-screen.error .conn-icon {
    color: var(--status-error);
  }

  .graph-overlay {
    position: fixed;
    inset: 0;
    z-index: 400;
    background-color: var(--bg-base);
    display: flex;
    flex-direction: column;
  }
</style>
