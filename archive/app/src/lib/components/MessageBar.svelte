<!--
  4.5 MessageBar.svelte
  Bottom message bar: tier selector + text input for agent launch / steer / queue.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import type { ModelModeKey } from '$types/index'
  import { PRIME_AGENT_ID } from '$types/index'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  const MODE_KEYS: ModelModeKey[] = ['low', 'medium', 'high']
  const MODE_LABELS: Record<ModelModeKey, string> = { low: 'L', medium: 'M', high: 'H' }

  let inputEl: HTMLTextAreaElement | undefined = $state()
  let draft = $state('')
  let sending = $state(false)

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

  /** Short display of the active model name for the mode bar. */
  const activeModelShort = $derived(() => {
    const m = appState.activeModelDisplay
    // Truncate long model names for the toolbar display
    if (m.length > 24) return m.slice(0, 22) + '…'
    return m
  })

  function selectMode(mode: ModelModeKey) {
    appState.setActiveModelMode(mode)
  }

  function openModelSettings() {
    window.dispatchEvent(new CustomEvent('taui:toggle-model-settings'))
  }

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
        ? `Message ${steerableAgent.displayName ?? 'agent'}…`
        : activeAgent
          ? `Message ${activeAgent.displayName ?? 'agent'}…`
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

  const replyTarget = $derived(isPrime ? appState.primeReplyTo : null)

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

        const outboundMessage = replyTarget
          ? buildReplyPrompt(replyTarget.role, replyTarget.content, msg)
          : msg

        // Start Prime streaming — the RPC returns immediately, and
        // tokens arrive via prime/token, prime/toolCall, prime/toolResult,
        // prime/done notifications handled in notifications.ts.
        appState.startPrimeStream(msg)
        try {
          const allMessages = [
            ...appState.primeMessages.map((m) => ({ role: m.role, content: m.content })),
            { role: 'user', content: outboundMessage },
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

  function truncateReply(text: string, maxLen = 180): string {
    const normalized = text.replace(/\s+/g, ' ').trim()
    if (normalized.length <= maxLen) return normalized
    return `${normalized.slice(0, maxLen - 1)}…`
  }

  function buildReplyPrompt(replyRole: 'user' | 'assistant', replyContent: string, message: string): string {
    const snippet = truncateReply(replyContent, 500)
    return `> [Replying to ${replyRole}]: ${snippet}\n\n${message}`
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

  {#if replyTarget}
    <div class="reply-preview">
      <div class="reply-preview-main">
        <span class="reply-preview-label">Replying to {replyTarget.role}</span>
        <span class="reply-preview-text">{truncateReply(replyTarget.content)}</span>
      </div>
      <button type="button" class="reply-preview-close" aria-label="Cancel reply" onclick={() => appState.clearPrimeReplyTo()}>✕</button>
    </div>
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
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="mode-toggle-group">
            <div class="mode-radios" role="radiogroup" aria-label="Model mode">
              {#each MODE_KEYS as mode}
                <button
                  class="mode-radio"
                  class:active={appState.activeModelMode === mode}
                  onclick={() => selectMode(mode)}
                  role="radio"
                  aria-checked={appState.activeModelMode === mode}
                  title="{mode} — {appState.modelModes[mode].primary.model}"
                >{MODE_LABELS[mode]}</button>
              {/each}
            </div>

            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <span class="mode-model-label" onclick={openModelSettings} title="Configure models">{appState.activeProviderDisplay}<span class="model-sep">/</span>{activeModelShort()}</span>
          </div>
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

  .reply-preview {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 8px;
    background: color-mix(in srgb, var(--fg-accent) 10%, var(--element-bg));
    border: 1px solid var(--border-variant);
    border-radius: 6px;
  }

  .reply-preview-main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 2px;
  }

  .reply-preview-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--fg-muted);
  }

  .reply-preview-text {
    font-size: 12px;
    color: var(--fg-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .reply-preview-close {
    border: 1px solid var(--border-variant);
    border-radius: 999px;
    width: 22px;
    height: 22px;
    background: var(--element-bg);
    color: var(--fg-muted);
    cursor: pointer;
  }

  .reply-preview-close:hover {
    color: var(--fg-primary);
    border-color: var(--border);
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
    border-color: var(--border);
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
    align-items: stretch;
    justify-content: space-between;
    padding: 0;
    border-top: 1px solid var(--border);
    overflow: hidden;
  }

  .toolbar-left {
    display: flex;
    align-items: stretch;
    gap: 0;
  }

  /* ── Mode toggle (L/M/H) ──────────────────────────────────────────────── */

  .mode-toggle-group {
    display: flex;
    align-items: stretch;
    gap: 0;
    padding: 0 4px 0 0;
  }

  .mode-radios {
    display: flex;
    align-items: stretch;
    gap: 0;
    flex-shrink: 0;
  }

  .mode-radio {
    width: 26px;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    border-top: none;
    border-bottom: none;
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
  .mode-radio:first-child { margin-left: 0; border-left: none; }
  .mode-radio:last-child { }
  .mode-radio:hover { background-color: var(--element-hover); color: var(--fg-primary); }
  .mode-radio.active { background-color: var(--element-selected); color: var(--fg-accent); border-color: var(--fg-accent); z-index: 1; }

  .mode-model-label {
    margin-left: 6px;
    font-size: 11px;
    color: var(--fg-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 220px;
    font-family: var(--font-mono);
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 3px;
    transition: color 0.1s, background-color 0.1s;
    align-self: center;
  }
  .mode-model-label:hover {
    color: var(--fg-primary);
    background-color: var(--element-hover);
  }

  .model-sep {
    opacity: 0.4;
    margin: 0 1px;
  }

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
    align-self: center;
    margin-right: 4px;
  }
  .send-btn:hover:not(:disabled) { background-color: #4a90c4; color: var(--bg-base); border-color: #4a90c4; }
  .send-btn:disabled { opacity: 0.3; cursor: not-allowed; }

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
