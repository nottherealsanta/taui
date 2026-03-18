<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { startConnection, stopConnection } from '$services/connection'
  import { appState } from '$stores/app-state.svelte'
  import { theme } from '$stores/theme.svelte'
  import TitleBar from '$components/TitleBar.svelte'
  import SpecTreePane from '$components/SpecTreePane.svelte'
  import AgentDetailPanel from '$components/AgentDetailPanel.svelte'
  import BottomDrawer from '$components/BottomDrawer.svelte'
  import MessageBar from '$components/MessageBar.svelte'
  import CommandPalette from '$components/CommandPalette.svelte'
  import QuickJump from '$components/QuickJump.svelte'
  import Toast from '$components/Toast.svelte'

  onMount(() => {
    startConnection()
    // Listen for menu events emitted from Tauri backend
    listenMenuEvents()
  })
  onDestroy(() => { stopConnection() })

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
  interface CodePreview {
    specRef?: string | null
    filePath: string
    content: string
    lineStart: number | null
    lineEnd: number | null
    language?: string
    truncated?: boolean
    previewStart?: number | null
    previewEnd?: number | null
  }
  let drawerOpen = $state(false)
  let codePreview: CodePreview | null = $state(null)

  function handleShowCode(preview: CodePreview) {
    codePreview = preview
    drawerOpen = true
  }

  // ── Agent detail panel ─────────────────────────────────────────────────────
  // Open when a node with an active agent is selected, or user explicitly opens.
  const detailAgentId = $derived(appState.detailAgentId)

  // ── Modals ─────────────────────────────────────────────────────────────────
  let showPalette = $state(false)
  let showJump = $state(false)

  // ── Global keybindings ─────────────────────────────────────────────────────
  function handleGlobalKeyDown(e: KeyboardEvent) {
    const meta = e.metaKey || e.ctrlKey
    if (!meta) return

    if (e.key === 'p' && !e.shiftKey) {
      // Cmd+P → Quick Jump (only when not typing in an input/textarea/monaco)
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      e.preventDefault()
      showJump = !showJump
      showPalette = false
    } else if (e.key === 'P' || (e.key === 'p' && e.shiftKey)) {
      // Cmd+Shift+P → Command Palette
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      e.preventDefault()
      showPalette = !showPalette
      showJump = false
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
    <!-- Primary spec tree pane -->
    <div class="main-area">
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
        <SpecTreePane onshowCode={handleShowCode} />
      {/if}
    </div>

    <!-- Agent detail panel (slide-in right) -->
    {#if detailAgentId !== null}
      <AgentDetailPanel
        agentId={detailAgentId}
        onclose={() => { appState.detailAgentId = null }}
      />
    {/if}
  </div>

  <!-- Bottom drawer (Code + Terminal) -->
  {#if drawerOpen}
    <BottomDrawer
      {codePreview}
      onclose={() => { drawerOpen = false; codePreview = null }}
    />
  {/if}

  <!-- Message bar -->
  <MessageBar />
</div>

<!-- Modals (outside app-shell to avoid stacking context issues) -->
{#if showPalette}
  <CommandPalette onclose={() => { showPalette = false }} />
{/if}
{#if showJump}
  <QuickJump onclose={() => { showJump = false }} />
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

  .main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
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
</style>
