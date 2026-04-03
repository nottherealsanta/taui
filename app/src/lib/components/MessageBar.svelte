<!--
  4.5 MessageBar.svelte
  Bottom message bar: tier selector + text input for agent launch / steer / queue.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import type { AgentTier } from '$types/index'
  import { PRIME_AGENT_ID } from '$types/index'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  const TIERS: AgentTier[] = ['low', 'medium', 'high']

  let inputEl: HTMLTextAreaElement | undefined = $state()
  let draft = $state('')
  let sending = $state(false)
  let providerDropdownOpen = $state(false)
  let modelDropdownOpen = $state(false)
  let dropdownPos = $state({ x: 0, y: 0 })

  const MODELS = [
    'claude-sonnet-4.6',
    'claude-opus-4.6',
    'gpt-5.3-codex',
    'gemini-3.1-pro-preview',
    'claude-haiku-4.5',
  ]

  interface SlashCommand {
    name: string
    usage: string
    description: string
  }

  const SLASH_COMMANDS: SlashCommand[] = [
    { name: 'new', usage: '/new [first message]', description: 'Start a fresh Prime context and draw a divider.' },
    { name: 'agent', usage: '/agent <task>', description: 'Force launch a root agent with the task.' },
    { name: 'root', usage: '/root <task>', description: 'Alias for /agent.' },
    { name: 'cancel', usage: '/cancel', description: 'Stop Prime\'s in-progress response.' },
    { name: 'help', usage: '/help', description: 'Show available slash commands.' },
  ]

  let slashActiveIndex = $state(0)

  const selectedRef = $derived(appState.selectedSpecRef)
  const isPrime = $derived(appState.detailAgentId === PRIME_AGENT_ID)

  /** Parse "provider:model" into separate parts. */
  const providerName = $derived(() => {
    const m = appState.currentModel
    if (!m) return ''
    const idx = m.indexOf(':')
    return idx >= 0 ? m.slice(0, idx) : ''
  })
  const modelName = $derived(() => {
    const m = appState.currentModel
    if (!m) return ''
    const idx = m.indexOf(':')
    return idx >= 0 ? m.slice(idx + 1) : m
  })

  const availableModels = () => MODELS

  /** Fallback to root spec ref when nothing is selected. */
  const launchRef = $derived(
    selectedRef ?? (appState.primaryRootId !== null ? appState.nodes[appState.primaryRootId]?.specRef ?? null : null)
  )

  const activeAgent = $derived(
    appState.detailAgentId && appState.detailAgentId !== PRIME_AGENT_ID
      ? appState.agents.get(appState.detailAgentId) ?? null
      : null
  )

  const steerableAgent = $derived(
    activeAgent && activeAgent.state !== 'idle' && activeAgent.state !== 'done'
      ? activeAgent
      : null
  )

  /** Status text for the status bar. */
  const statusText = $derived(() => {
    if (isPrime && (sending || appState.primeStreaming)) return 'thinking…'
    if (steerableAgent) {
      const s = steerableAgent.state
      if (s === 'thinking') return 'thinking…'
      if (s === 'running') return 'working on it…'
      if (s === 'tool_execution') return steerableAgent.toolBrief ? `running ${steerableAgent.toolBrief}…` : 'executing…'
      if (s === 'asking_question' || s === 'waiting_for_answer') return 'waiting for answer…'
      if (s === 'stopping') return 'stopping…'
    }
    return ''
  })

  const placeholder = $derived(
    isPrime
      ? `Message Prime…`
      : steerableAgent
        ? `Steer active agent (Shift+Enter to queue)…`
        : `Send a message…`
  )

  const slashToken = $derived(() => {
    if (!isPrime) return null
    const trimmed = draft.trimStart()
    if (!trimmed.startsWith('/')) return null
    const firstSpace = trimmed.indexOf(' ')
    if (firstSpace >= 0) return null
    return trimmed.slice(1).toLowerCase()
  })

  const filteredSlashCommands = $derived(() => {
    const token = slashToken()
    if (token === null) return []
    return SLASH_COMMANDS.filter((cmd) => cmd.name.startsWith(token))
  })

  const slashSuggestionsOpen = $derived(
    isPrime && !sending && !appState.primeStreaming && slashToken() !== null && filteredSlashCommands().length > 0
  )

  $effect(() => {
    const count = filteredSlashCommands().length
    if (count === 0 || !slashSuggestionsOpen) {
      slashActiveIndex = 0
      return
    }
    if (slashActiveIndex >= count) {
      slashActiveIndex = 0
    }
  })

  function toggleProviderDropdown(e: MouseEvent) {
    if (!providerDropdownOpen) {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
      dropdownPos = { x: rect.left, y: rect.top }
    }
    providerDropdownOpen = !providerDropdownOpen
    modelDropdownOpen = false
  }

  function toggleModelDropdown(e: MouseEvent) {
    if (!modelDropdownOpen) {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
      dropdownPos = { x: rect.left, y: rect.top }
    }
    modelDropdownOpen = !modelDropdownOpen
    providerDropdownOpen = false
  }

  function closeDropdowns() {
    providerDropdownOpen = false
    modelDropdownOpen = false
  }

  function selectProvider(p: string) {
    const firstModel = MODELS[0] ?? ''
    appState.currentModel = `${p}:${firstModel}`
    providerDropdownOpen = false
  }

  function selectModel(m: string) {
    const p = providerName()
    appState.currentModel = p ? `${p}:${m}` : m
    modelDropdownOpen = false
  }

  function parseSlashCommand(text: string): { name: string; args: string } | null {
    const trimmed = text.trim()
    const m = /^\/([a-zA-Z]+)(?:\s+([\s\S]*))?$/.exec(trimmed)
    if (!m) return null
    return {
      name: m[1].toLowerCase(),
      args: (m[2] ?? '').trim(),
    }
  }

  function insertSlashCommand(cmd: SlashCommand) {
    draft = `/${cmd.name} `
    slashActiveIndex = 0
    tick().then(() => {
      inputEl?.focus()
      if (inputEl) {
        inputEl.style.height = 'auto'
        inputEl.style.height = inputEl.scrollHeight + 'px'
      }
    })
  }

  async function runPrimeSlashCommand(cmd: { name: string; args: string }) {
    if (cmd.name === 'help') {
      const text = [
        'Available commands:',
        ...SLASH_COMMANDS.map((c) => `- ${c.usage}: ${c.description}`),
      ].join('\n')
      appState.addPrimeAssistantMessage(text)
      return
    }

    if (cmd.name === 'cancel') {
      await backendClient.primeCancel()
      appState.addPrimeAssistantMessage('Cancelled current Prime response.')
      return
    }

    if (cmd.name === 'new') {
      appState.addPrimeContextDivider('New context')
      const newCtx = await backendClient.primeNewContext(cmd.args || undefined)

      if (newCtx.unsupported) {
        // Older backend: best-effort boundary in UI plus cancel in-flight response.
        await backendClient.primeCancel()
        appState.addPrimeAssistantMessage('Started a visual new context. Full context reset requires restarting the backend.')
      }

      if (cmd.args) {
        appState.startPrimeStream(cmd.args)
        try {
          await backendClient.primeMessage([{ role: 'user', content: cmd.args }])
        } catch (e) {
          console.error('[MessageBar] prime /new seed failed:', e)
          appState.appendPrimeStreamToken(`Error: ${e}`)
          appState.finalizePrimeStream()
        }
      }
      return
    }

    if (cmd.name === 'agent' || cmd.name === 'root') {
      if (!cmd.args) {
        appState.addPrimeAssistantMessage('Usage: /agent <task>')
        return
      }
      const ref = launchRef
      if (!ref) {
        appState.addPrimeAssistantMessage('Cannot launch root agent: no active root spec selected.')
        return
      }

      const result = await backendClient.agentLaunch(ref, cmd.args, appState.launchTier)
      appState.upsertAgent({
        agentId: result.agentId,
        specRef: ref,
        state: 'running',
        tier: appState.launchTier as 'high' | 'medium' | 'low',
      })
      appState.addPrimeAgentLaunched({
        agentId: result.agentId,
        displayName: result.agentId,
        task: cmd.args,
      })
      return
    }

    appState.addPrimeAssistantMessage(`Unknown slash command: /${cmd.name}. Use /help.`)
  }

  async function submit() {
    const msg = draft.trim()
    if (!msg || sending || appState.primeStreaming) return
    sending = true
    draft = ''

    try {
      if (isPrime) {
        const slash = parseSlashCommand(msg)
        if (slash) {
          await runPrimeSlashCommand(slash)
          return
        }

        // Start Prime streaming — the RPC returns immediately, and
        // tokens arrive via prime/token, prime/toolCall, prime/toolResult,
        // prime/done notifications handled in notifications.ts.
        appState.startPrimeStream(msg)
        try {
          const allMessages = [
            ...appState.primeMessages.map((m) => ({ role: m.role, content: m.content })),
            { role: 'user', content: msg },
          ]
          await backendClient.primeMessage(allMessages)
          // Actual response arrives via notifications — nothing to await here.
        } catch (e) {
          console.error('[MessageBar] prime failed:', e)
          // Emit an error token and finalize so the UI isn't stuck in streaming state
          appState.appendPrimeStreamToken(`Error: ${e}`)
          appState.finalizePrimeStream()
        }
      } else if (steerableAgent) {
        // Steer running agent
        await backendClient.agentSteer(steerableAgent.agentId, msg)
      } else {
        const ref = launchRef
        if (!ref) return
        // Launch new agent and open detail panel
        const result = await backendClient.agentLaunch(ref, msg, appState.launchTier)
        // Pre-register agent so the tab appears immediately (before stateChanged notification)
        appState.upsertAgent({
          agentId: result.agentId,
          specRef: ref,
          state: 'running',
          tier: appState.launchTier as 'high' | 'medium' | 'low',
        })
        appState.detailAgentId = result.agentId
      }
    } catch (e) {
      console.error('[MessageBar] send failed:', e)
    } finally {
      sending = false
      await tick()
      if (inputEl) inputEl.style.height = 'auto'
      inputEl?.focus()
    }
  }

  async function submitQueue() {
    const msg = draft.trim()
    if (!msg || !steerableAgent || sending) return
    sending = true
    draft = ''
    try {
      await backendClient.agentQueue(steerableAgent.agentId, msg)
    } catch (e) {
      console.error('[MessageBar] queue failed:', e)
    } finally {
      sending = false
      await tick()
      if (inputEl) inputEl.style.height = 'auto'
      inputEl?.focus()
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (isPrime && slashSuggestionsOpen && !e.shiftKey) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        slashActiveIndex = (slashActiveIndex + 1) % filteredSlashCommands().length
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        slashActiveIndex = (slashActiveIndex - 1 + filteredSlashCommands().length) % filteredSlashCommands().length
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        slashActiveIndex = 0
        return
      }

      const trimmed = draft.trimStart()
      const selectingCommandOnly = trimmed.startsWith('/') && !trimmed.includes(' ')
      if ((e.key === 'Enter' || e.key === 'Tab') && selectingCommandOnly) {
        e.preventDefault()
        const selected = filteredSlashCommands()[slashActiveIndex]
        if (selected) insertSlashCommand(selected)
        return
      }
    }

    if (e.key === 'Enter' && e.shiftKey && steerableAgent) {
      // Shift+Enter = queue (only when agent is active)
      e.preventDefault()
      submitQueue()
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function autoResize(e: Event) {
    const el = e.target as HTMLTextAreaElement
    el.style.height = 'auto'
    el.style.height = el.scrollHeight + 'px'
  }
</script>

<div class="status-bar">
  {#if statusText()}
    <span class="status-dot"></span>
    <span class="status-text">{statusText()}</span>
  {/if}
</div>

<div class="message-bar-shell">
  <!-- Tool brief (ephemeral, from active agent) -->
  {#if steerableAgent?.toolBrief}
    <div class="tool-brief">{steerableAgent.toolBrief}</div>
  {/if}

  <div class="input-row">
    <div class="input-wrapper">
      {#if slashSuggestionsOpen}
        <div class="slash-suggestions">
          {#each filteredSlashCommands() as cmd, idx (cmd.name)}
            <button
              type="button"
              class="slash-item"
              class:active={idx === slashActiveIndex}
              onclick={() => insertSlashCommand(cmd)}
            >
              <span class="slash-name">/{cmd.name}</span>
              <span class="slash-description">{cmd.description}</span>
            </button>
          {/each}
        </div>
      {/if}

      <textarea
        bind:this={inputEl}
        bind:value={draft}
        class="message-input selectable"
        rows="1"
        {placeholder}
        disabled={sending || appState.primeStreaming || (!isPrime && !selectedRef && !steerableAgent)}
        onkeydown={onKeydown}
        oninput={autoResize}
        autocomplete="off"
        spellcheck="false"
      ></textarea>

      <div class="input-toolbar">
        <div class="toolbar-left">
          {#if appState.currentModel}
            <div class="model-info">
              {#if providerDropdownOpen || modelDropdownOpen}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="dropdown-backdrop" onclick={closeDropdowns}></div>
              {/if}

              <!-- Provider selector -->
              <span class="selector-group">
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <span class="toolbar-btn provider-selector" onclick={toggleProviderDropdown}>
                  {providerName() || 'provider'}
                </span>
              </span>

              <!-- Model selector -->
              <span class="selector-group">
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <span class="toolbar-btn model-selector" onclick={toggleModelDropdown}>
                  {modelName() || 'model'}
                </span>
              </span>
            </div>
          {/if}

          {#if !isPrime && !steerableAgent}
            <div class="tier-radios" role="radiogroup" aria-label="Agent tier">
              {#each TIERS as tier}
                <button
                  class="tier-radio"
                  class:active={appState.launchTier === tier}
                  onclick={() => { appState.launchTier = tier }}
                  role="radio"
                  aria-checked={appState.launchTier === tier}
                >{tier === 'low' ? 'L' : tier === 'medium' ? 'M' : 'H'}</button>
              {/each}
            </div>
          {:else if steerableAgent}
            <div class="agent-indicator">
              <span class="agent-dot"></span>
              <span class="agent-label">{steerableAgent.tier}</span>
            </div>
          {/if}
        </div>

        <button
          class="send-btn"
          onclick={submit}
          disabled={!draft.trim() || sending || appState.primeStreaming || (!isPrime && !selectedRef && !steerableAgent)}
          aria-label="Send"
        >
          {sending || appState.primeStreaming ? '…' : '↑'}
        </button>
      </div>
    </div>
  </div>
</div>

{#if providerDropdownOpen || modelDropdownOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="dropdown-backdrop" onclick={closeDropdowns}></div>
{/if}

{#if providerDropdownOpen}
  <div class="dropdown fixed-dropdown" style="left: {dropdownPos.x}px; top: {dropdownPos.y}px;">
    {#each ['copilot'] as p}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="dropdown-item"
        class:active={providerName() === p}
        onclick={() => selectProvider(p)}
      >{p}</div>
    {/each}
  </div>
{/if}

{#if modelDropdownOpen}
  <div class="dropdown fixed-dropdown" style="left: {dropdownPos.x}px; top: {dropdownPos.y}px;">
    {#each availableModels() as m}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="dropdown-item"
        class:active={modelName() === m}
        onclick={() => selectModel(m)}
      >{m}</div>
    {/each}
  </div>
{/if}

<style lang="postcss">
  .message-bar-shell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    /* padding: 4px 6px; */
  }

  .tool-brief {
    font-size: 11px;
    color: var(--fg-muted);
    padding: 4px 8px;
    background-color: var(--element-bg);
    border-radius: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
  }

  .input-wrapper {
    flex: 1;
    min-width: 0;
    position: relative;
    display: flex;
    flex-direction: column;
    background: var(--element-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    transition: border-color 0.15s, box-shadow 0.15s;
    overflow: hidden;
  }
  .input-wrapper:focus-within {
    border-color: #4a90c4;
    box-shadow: 0 0 0 1px #4a90c433;
  }

  .status-bar {
    bottom: 100%;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 16px 12px 6px 12px;
    background: linear-gradient(to bottom, transparent, var(--bg-base));
    font-size: 12px;
    color: var(--fg-muted);
    pointer-events: none;
    z-index: 1;
  }
  .status-bar > * {
    pointer-events: auto;
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--fg-accent);
    animation: pulse 1.5s ease-in-out infinite;
    flex-shrink: 0;
  }

  .status-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .message-input {
    flex: 1;
    min-width: 0;
    min-height: calc(1 * 1.4em + 16px);
    max-height: calc(7 * 1.4em + 16px);
    overflow-y: auto;
    resize: none;
    background: transparent;
    border: none;
    padding: 12px 12px 8px 12px;
    font-size: 14px;
    line-height: 1.4;
    font-family: var(--font-sans);
    color: var(--fg-primary);
    outline: none;
    field-sizing: content;
  }
  .message-input::placeholder { color: var(--fg-muted); }
  .message-input:disabled { opacity: 0.5; cursor: not-allowed; }

  .slash-suggestions {
    display: flex;
    flex-direction: column;
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--bg-surface) 90%, var(--element-bg));
    max-height: 180px;
    overflow-y: auto;
  }

  .slash-item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    border: none;
    border-bottom: 1px solid var(--border-variant);
    background: transparent;
    padding: 8px 12px;
    text-align: left;
    cursor: pointer;
    color: var(--fg-primary);
  }

  .slash-item:last-child {
    border-bottom: none;
  }

  .slash-item:hover,
  .slash-item.active {
    background: var(--element-hover);
  }

  .slash-name {
    min-width: 70px;
    font-size: 12px;
    font-weight: 600;
    color: var(--fg-accent);
    font-family: var(--font-mono);
  }

  .slash-description {
    font-size: 12px;
    color: var(--fg-muted);
  }

  .input-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0;
    border-top: 1px solid var(--border);
  }

  .toolbar-left {
    display: flex;
    align-items: stretch;
    gap: 0;
  }

  .toolbar-btn {
    font-size: 11px;
    color: var(--fg-muted);
    cursor: pointer;
    user-select: none;
    padding: 5px 10px;
    border: none;
    border-right: 1px solid var(--border);
    border-radius: 0;
    transition: all 0.1s;
  }
  .toolbar-btn:hover {
    color: var(--fg-primary);
    background-color: var(--element-hover);
  }

  .tier-radios {
    display: flex;
    gap: 0;
    flex-shrink: 0;
  }

  .tier-radio {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    border-radius: 0;
    background: transparent;
    color: var(--fg-muted);
    font-size: 11px;
    font-weight: 600;
    font-family: var(--font-sans);
    cursor: pointer;
    transition: all 0.1s;
    margin-left: -1px;
  }
  .tier-radio:first-child { margin-left: 0; border-radius: 4px 0 0 4px; }
  .tier-radio:last-child { border-radius: 0 4px 4px 0; }
  .tier-radio:hover { background-color: var(--element-hover); color: var(--fg-primary); }
  .tier-radio.active { background-color: var(--element-selected); color: var(--fg-accent); border-color: var(--fg-accent); z-index: 1; }

  .agent-indicator {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
    height: 26px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background-color: transparent;
  }

  .agent-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: var(--status-in-progress);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .agent-label { font-size: 11px; color: var(--fg-muted); }

  .send-btn {
    width: 28px;
    height: 28px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    color: var(--fg-muted);
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: all 0.15s;
  }
  .send-btn:hover:not(:disabled) { background-color: #4a90c4; color: var(--bg-base); border-color: #4a90c4; }
  .send-btn:disabled { opacity: 0.3; cursor: not-allowed; }

  /* ── Model info ─────────────────────────────────────────────────────────── */

  .model-info {
    position: relative;
    display: flex;
    align-items: stretch;
    gap: 0;
  }

  .selector-group {
    position: relative;
  }

  .dropdown-backdrop {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .dropdown {
    min-width: 160px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    z-index: 100;
    padding: 4px 0;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }

  .fixed-dropdown {
    position: fixed;
    transform: translateY(-100%) translateY(-4px);
  }

  .dropdown-item {
    padding: 6px 12px;
    font-size: 12px;
    color: var(--fg-primary);
    cursor: pointer;
    white-space: nowrap;
  }
  .dropdown-item:hover {
    background-color: var(--element-hover);
  }
  .dropdown-item.active {
    color: var(--fg-accent);
  }

  @media (max-width: 900px) {
    .input-row {
      flex-wrap: wrap;
    }
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
