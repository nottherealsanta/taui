/**
 * Central application state, implemented with Svelte 5 $state runes.
 * Ported from ui/src/app/state.rs.
 *
 * All mutations live here; components read via derived getters.
 */

import type {
  NodeId,
  SpecRef,
  SpecNode,
  FlatNode,
  AgentInfo,
  AgentState,
  AgentTier,
  PendingQuestion,
  AgentDetailEvent,
  EditorMode,
  MetadataEditTarget,
  BackendConnectionState,
  BackendNode,
  RunState,
  RunLine,
  PrimeMessage,
  PrimeToolCall,
  PrimeSubAgentEntry,
  PrimeChatEntry,
  PrimeHistoryMessage,
  PrimeReplyTarget,
} from '$types/index'
import { agentStateIsActive, agentStateFromString, PRIME_AGENT_ID } from '$types/index'

// ─── AppState class ───────────────────────────────────────────────────────────

class AppState {
  // Tree storage
  nodes: SpecNode[] = $state([])
  rootNodes: NodeId[] = $state([])
  specRefIndex: Map<SpecRef, NodeId> = $state(new Map())

  // Selection
  selectedNode: NodeId | null = $state(null)
  selectedSpecRef: SpecRef | null = $state(null)
  editorMode: EditorMode = $state('normal')

  // Chat / message bar
  chatDraft: string = $state('')

  // Backend
  connectionState: BackendConnectionState = $state('offline')

  // Agents
  agents: Map<string, AgentInfo> = $state(new Map())
  lockedBranches: Set<SpecRef> = $state(new Set())
  pendingQuestions: PendingQuestion[] = $state([])
  detailEvents: Map<string, AgentDetailEvent[]> = $state(new Map())
  detailAgentId: string | null = $state(PRIME_AGENT_ID)

  // Prime
  primeMessages: PrimeMessage[] = $state([])

  // Prime streaming state
  primeStreaming: boolean = $state(false)
  primeStreamBuffer: string = $state('')
  primeChatEntries: PrimeChatEntry[] = $state([])
  primeToolCalls: Map<string, PrimeToolCall> = $state(new Map())
  primeSubAgents: Map<string, PrimeSubAgentEntry> = $state(new Map())
  primeHistoryHasMore: boolean = $state(false)
  primeOldestSeq: number | null = $state(null)
  primeHistoryLoading: boolean = $state(false)
  primeReplyTo: PrimeReplyTarget | null = $state(null)

  // Launch tier
  launchTier: AgentTier = $state('medium')

  // Current model
  currentModel: string = $state('')

  // Inline metadata editing target
  metadataEditTarget: MetadataEditTarget | null = $state(null)

  // Run / Terminal
  runState: RunState = $state({
    status: 'idle',
    runId: null,
    specRef: null,
    command: null,
    exitCode: null,
    lines: [],
  })

  // ── Derived ────────────────────────────────────────────────────────────────

  /** Human-readable primary root title (first line of root markdown). */
  get rootTitle(): string {
    const rootId = this.primaryRootId
    if (rootId === null) return 'Taui'
    return this.nodes[rootId]?.markdown.split('\n')[0].trim() || 'Taui'
  }

  get primaryRootId(): NodeId | null {
    return this.rootNodes[0] ?? null
  }

  /** All visible nodes as a flat list for the tree view. */
  get flattenedNodes(): FlatNode[] {
    const out: FlatNode[] = []
    for (const rootId of this.rootNodes) {
      this._collectFlat(rootId, 0, false, out)
    }
    return out
  }

  /**
   * Same as flattenedNodes but skips the primary root row itself —
   * its children start at depth 1. Secondary roots render at depth 1.
   */
  get flattenedTreeNodes(): FlatNode[] {
    const out: FlatNode[] = []
    const rootId = this.primaryRootId
    for (const rid of this.rootNodes) {
      if (rid === rootId) {
        for (const childId of this.nodes[rid]?.children ?? []) {
          this._collectFlat(childId, 1, false, out)
        }
      } else {
        this._collectFlat(rid, 1, false, out)
      }
    }
    return out
  }

  // ── Tree helpers ──────────────────────────────────────────────────────────

  siblings(parent: NodeId | null): NodeId[] {
    if (parent === null) return this.rootNodes
    return this.nodes[parent]?.children ?? []
  }

  // ── Mutations ─────────────────────────────────────────────────────────────

  createNode(specRef: SpecRef, markdown: string, parent: NodeId | null): NodeId {
    const id = this.nodes.length
    this.specRefIndex.set(specRef, id)
    this.nodes.push({
      id,
      specRef,
      markdown,
      parent,
      children: [],
      collapsed: false,
      status: null,
      codeRefs: [],
      verification: null,
      dependsOn: [],
      relatedTo: [],
    })
    return id
  }

  setSelected(id: NodeId): void {
    this.selectedNode = id
    this.selectedSpecRef = this.nodes[id]?.specRef ?? null
  }

  clearSelection(): void {
    this.selectedNode = null
    this.selectedSpecRef = null
    this.editorMode = 'normal'
  }

  toggleCollapse(): boolean {
    const selected = this.selectedNode
    if (selected === null) return false
    if (selected === this.primaryRootId) return false
    const node = this.nodes[selected]
    if (!node || node.children.length === 0) return false
    node.collapsed = !node.collapsed
    return true
  }

  /**
   * Hydrate the full tree state from a `spec/getTreeDetailed` response.
   * Mirrors the Rust `hydrate_from_backend` method closely.
   */
  hydrateFromBackend(rawNodes: BackendNode[]): void {
    const prevSelectedRef = this.selectedSpecRef

    this.nodes = []
    this.rootNodes = []
    this.specRefIndex = new Map()

    if (rawNodes.length === 0) {
      this.connectionState = 'ready'
      return
    }

    // Normalise depths so the shallowest node is always depth 0.
    const minDepth = Math.min(...rawNodes.map((n) => n.depth))

    const depthStack: Array<NodeId | null> = []

    for (const bn of rawNodes) {
      const depth = bn.depth - minDepth
      const parentId = depth === 0 ? null : (depthStack[depth - 1] ?? null)

      const id = this.createNode(bn.spec_ref, bn.markdown, parentId)

      // Start fully expanded; persisted local fold state is applied after hydration.
      this.nodes[id].collapsed = false
      this.nodes[id].status = bn.status ?? null
      this.nodes[id].codeRefs = bn.code_refs ?? []
      this.nodes[id].verification = bn.verification ?? null
      this.nodes[id].dependsOn = bn.depends_on ?? []
      this.nodes[id].relatedTo = bn.related_to ?? []

      if (parentId !== null) {
        this.nodes[parentId].children.push(id)
      } else {
        this.rootNodes.push(id)
      }

      // Maintain depth stack.
      depthStack[depth] = id
      depthStack.length = depth + 1
    }

    // Restore previous selection if the spec_ref still exists.
    if (prevSelectedRef) {
      const prevId = this.specRefIndex.get(prevSelectedRef)
      if (prevId !== undefined) {
        this.selectedNode = prevId
        this.selectedSpecRef = prevSelectedRef
      }
    }

    // Drop empty root placeholder nodes.
    this.rootNodes = this.rootNodes.filter((id) => {
      const n = this.nodes[id]
      return n && (n.markdown.trim() !== '' || n.children.length > 0)
    })

    // Always expand the primary root.
    const rootId = this.primaryRootId
    if (rootId !== null) {
      this.nodes[rootId].collapsed = false
    }

    this.connectionState = 'ready'
  }

  /**
   * Apply a single node change notification from `spec/nodeChanged`.
   */
  applyNodeChange(bn: BackendNode): void {
    const existingId = this.specRefIndex.get(bn.spec_ref)
    if (existingId !== undefined) {
      const node = this.nodes[existingId]
      node.markdown = bn.markdown
      node.status = bn.status ?? null
      node.codeRefs = bn.code_refs ?? []
      node.verification = bn.verification ?? null
      node.dependsOn = bn.depends_on ?? []
      node.relatedTo = bn.related_to ?? []
    }
  }

  // ── Agent mutations ────────────────────────────────────────────────────────

  upsertAgent(info: Partial<AgentInfo> & { agentId: string }): void {
    const existing = this.agents.get(info.agentId)
    if (existing) {
      Object.assign(existing, info)
    } else {
      this.agents.set(info.agentId, {
        agentId: info.agentId,
        specRef: info.specRef ?? '',
        state: info.state ?? 'idle',
        tier: info.tier ?? 'medium',
        toolBrief: info.toolBrief ?? null,
        agentType: info.agentType ?? 'root',
        displayName: info.displayName ?? info.agentId,
      })
    }
  }

  setAgentState(agentId: string, state: AgentState): void {
    const agent = this.agents.get(agentId)
    if (agent) agent.state = state
  }

  setToolBrief(agentId: string, brief: string | null): void {
    const agent = this.agents.get(agentId)
    if (agent) agent.toolBrief = brief
  }

  setLockedBranches(branches: SpecRef[]): void {
    this.lockedBranches = new Set(branches)
  }

  addPendingQuestion(q: PendingQuestion): void {
    this.pendingQuestions = [...this.pendingQuestions.filter((p) => p.agentId !== q.agentId), q]
  }

  removePendingQuestion(agentId: string): void {
    this.pendingQuestions = this.pendingQuestions.filter((q) => q.agentId !== agentId)
  }

  appendDetailEvent(agentId: string, event: AgentDetailEvent): void {
    const existing = this.detailEvents.get(agentId)
    if (existing) {
      existing.push(event)
    } else {
      this.detailEvents.set(agentId, [event])
    }
  }

  setDetailBacklog(agentId: string, events: AgentDetailEvent[]): void {
    this.detailEvents.set(agentId, events)
  }

  // ── Prime mutations ────────────────────────────────────────────────────────

  /** Restore Prime conversation history from backend (on reconnect/refresh). */
  restorePrimeHistory(
    messages: PrimeHistoryMessage[],
    opts?: { hasMore?: boolean; oldestSeq?: number | null },
  ): void {
    const built = this._buildPrimeEntriesFromHistory(messages)
    this.primeChatEntries = built.entries
    this.primeMessages = built.primeMessages
    this.primeToolCalls = built.toolCalls
    this.primeOldestSeq = opts?.oldestSeq ?? this._inferOldestSeq(messages)
    this.primeHistoryHasMore = opts?.hasMore ?? false
  }

  prependPrimeHistoryPage(messages: PrimeHistoryMessage[], hasMore: boolean, oldestSeq: number | null): void {
    const built = this._buildPrimeEntriesFromHistory(messages)
    this.primeChatEntries = [...built.entries, ...this.primeChatEntries]

    for (const msg of built.primeMessages) {
      this.primeMessages = [msg, ...this.primeMessages]
    }
    for (const [callId, tool] of built.toolCalls.entries()) {
      this.primeToolCalls.set(callId, tool)
    }

    this.primeHistoryHasMore = hasMore
    this.primeOldestSeq = oldestSeq
  }

  setPrimeHistoryLoading(value: boolean): void {
    this.primeHistoryLoading = value
  }

  setPrimeReplyTo(target: PrimeReplyTarget | null): void {
    this.primeReplyTo = target
  }

  clearPrimeReplyTo(): void {
    this.primeReplyTo = null
  }

  addPrimeMessage(msg: PrimeMessage): void {
    this.primeMessages = [...this.primeMessages, msg]
  }

  /** Append an assistant message directly into Prime chat/history. */
  addPrimeAssistantMessage(content: string): void {
    this.primeChatEntries = [...this.primeChatEntries, { kind: 'assistant', content }]
    this.primeMessages = [...this.primeMessages, { role: 'assistant', content }]
  }

  /** Visually separates Prime chat into a new context boundary. */
  addPrimeContextDivider(label = 'New context'): void {
    this.primeChatEntries = [...this.primeChatEntries, { kind: 'context-divider', label }]
  }

  /** Start a new Prime streaming response. Called when user sends a message. */
  startPrimeStream(userMessage: string): void {
    this.primeStreaming = true
    this.primeStreamBuffer = ''
    this.primeReplyTo = null
    this.primeChatEntries = [...this.primeChatEntries, { kind: 'user', content: userMessage }]
  }

  /** Append a token to the current streaming buffer. */
  appendPrimeStreamToken(text: string): void {
    this.primeStreamBuffer += text
    // Update the last streaming entry or create one
    const last = this.primeChatEntries[this.primeChatEntries.length - 1]
    if (last?.kind === 'assistant-streaming') {
      last.content = this.primeStreamBuffer
    } else {
      this.primeChatEntries = [
        ...this.primeChatEntries,
        { kind: 'assistant-streaming', content: this.primeStreamBuffer },
      ]
    }
  }

  /** Add a tool call entry to the Prime chat stream. */
  addPrimeToolCall(tool: PrimeToolCall): void {
    this.primeToolCalls.set(tool.callId, tool)
    this.primeChatEntries = [...this.primeChatEntries, { kind: 'tool', tool }]
  }

  /** Complete a Prime tool call with result. */
  completePrimeToolCall(result: {
    callId: string
    output: string | null
    error: string | null
    durationMs: number | null
  }): void {
    const tool = this.primeToolCalls.get(result.callId)
    if (tool) {
      tool.result = result.output
      tool.error = result.error
      tool.durationMs = result.durationMs
      tool.status = result.error ? 'error' : 'done'
    }
    // Also update the entry in primeChatEntries
    for (const entry of this.primeChatEntries) {
      if (entry.kind === 'tool' && entry.tool.callId === result.callId) {
        entry.tool.result = result.output
        entry.tool.error = result.error
        entry.tool.durationMs = result.durationMs
        entry.tool.status = result.error ? 'error' : 'done'
      }
    }
  }

  /** Add a sub-agent entry to the Prime chat stream. */
  addPrimeSubAgent(subAgent: PrimeSubAgentEntry): void {
    this.primeSubAgents.set(subAgent.subAgentId, subAgent)
    this.primeChatEntries = [...this.primeChatEntries, { kind: 'sub_agent', subAgent }]
  }

  /** Complete a Prime sub-agent with its result. */
  completePrimeSubAgent(subAgentId: string, result: string | null): void {
    const subAgent = this.primeSubAgents.get(subAgentId)
    if (subAgent) {
      subAgent.status = 'done'
      subAgent.result = result
    }
    for (const entry of this.primeChatEntries) {
      if (entry.kind === 'sub_agent' && entry.subAgent.subAgentId === subAgentId) {
        entry.subAgent.status = 'done'
        entry.subAgent.result = result
      }
    }
  }

  /** Add an agent-launched notification to Prime's chat. */
  addPrimeAgentLaunched(info: { agentId: string; displayName: string; task: string }): void {
    this.primeChatEntries = [...this.primeChatEntries, {
      kind: 'agent-launched',
      agentId: info.agentId,
      displayName: info.displayName,
      task: info.task,
    }]
  }

  /** Finalize the streaming response — convert streaming entry to final assistant message. */
  finalizePrimeStream(): void {
    const content = this.primeStreamBuffer
    if (content) {
      // Replace the streaming entry with a final assistant entry
      this.primeChatEntries = this.primeChatEntries.map((e) =>
        e.kind === 'assistant-streaming' ? { kind: 'assistant' as const, content: e.content } : e,
      )
      // Also add to legacy primeMessages for backwards compat
      this.primeMessages = [...this.primeMessages, { role: 'assistant', content }]
    }
    this.primeStreaming = false
    this.primeStreamBuffer = ''
  }

  private _buildPrimeEntriesFromHistory(messages: PrimeHistoryMessage[]): {
    entries: PrimeChatEntry[]
    primeMessages: PrimeMessage[]
    toolCalls: Map<string, PrimeToolCall>
  } {
    const entries: PrimeChatEntry[] = []
    const primeMessages: PrimeMessage[] = []
    const toolCalls = new Map<string, PrimeToolCall>()
    const assistantToolMeta = new Map<string, { toolName: string; arguments: unknown }>()

    for (const msg of messages) {
      const seq = msg.seq ?? null

      if (msg.role === 'divider') {
        entries.push({ kind: 'context-divider', label: msg.content || 'New context', seq })
        continue
      }

      if (msg.role === 'user') {
        entries.push({ kind: 'user', content: msg.content, seq })
        primeMessages.push({ role: 'user', content: msg.content })
        continue
      }

      if (msg.role === 'assistant') {
        const toolCallsMeta = msg.metadata?.['tool_calls']
        if (Array.isArray(toolCallsMeta)) {
          for (const item of toolCallsMeta) {
            if (!item || typeof item !== 'object') continue
            const obj = item as Record<string, unknown>
            const callId = typeof obj['id'] === 'string' ? obj['id'] : ''
            if (!callId) continue

            const fn = obj['function'] as Record<string, unknown> | undefined
            const toolName = typeof fn?.['name'] === 'string' ? fn['name'] : ''
            let args: unknown = {}
            if (typeof fn?.['arguments'] === 'string') {
              try {
                args = JSON.parse(fn['arguments'])
              } catch {
                args = fn['arguments']
              }
            }
            assistantToolMeta.set(callId, { toolName, arguments: args })
          }
        }

        const assistantContent = (msg.content ?? '').trim()
        if (assistantContent.length > 0) {
          entries.push({ kind: 'assistant', content: msg.content, seq })
          primeMessages.push({ role: 'assistant', content: msg.content })
        }
        continue
      }

      if (msg.role === 'tool') {
        const callId = msg.tool_call_id ?? ''
        const toolName =
          (typeof msg.name === 'string' && msg.name) ||
          (typeof msg.metadata?.['tool_name'] === 'string' ? msg.metadata['tool_name'] : '') ||
          assistantToolMeta.get(callId)?.toolName ||
          'tool'
        const args =
          msg.metadata?.['arguments'] ??
          assistantToolMeta.get(callId)?.arguments ??
          {}

        const tool: PrimeToolCall = {
          callId,
          toolName,
          arguments: args,
          result: msg.content,
          error: null,
          durationMs: null,
          status: 'done',
        }
        toolCalls.set(callId, tool)
        entries.push({ kind: 'tool', tool, seq })
      }
    }

    return { entries, primeMessages, toolCalls }
  }

  private _inferOldestSeq(messages: PrimeHistoryMessage[]): number | null {
    for (const msg of messages) {
      if (typeof msg.seq === 'number') {
        return msg.seq
      }
    }
    return null
  }

  // ── Run mutations ─────────────────────────────────────────────────────────

  setRunStatus(status: RunState['status'], runId?: number | null, specRef?: SpecRef | null, command?: string | null, exitCode?: number | null): void {
    this.runState.status = status
    if (runId !== undefined) this.runState.runId = runId
    if (specRef !== undefined) this.runState.specRef = specRef
    if (command !== undefined) this.runState.command = command
    if (exitCode !== undefined) this.runState.exitCode = exitCode
  }

  addRunLine(line: RunLine): void {
    this.runState.lines = [...this.runState.lines, line]
  }

  clearRunOutput(): void {
    this.runState.lines = []
    this.runState.exitCode = null
  }

  // ── Private tree traversal ────────────────────────────────────────────────

  private _collectFlat(
    nodeId: NodeId,
    depth: number,
    ancestorSelected: boolean,
    out: FlatNode[],
  ): void {
    const node = this.nodes[nodeId]
    if (!node) return

    const isSelected = this.selectedNode === nodeId
    const selectionHighlighted = isSelected || ancestorSelected

    const specRef = node.specRef
    let agentId: string | null = null
    for (const a of this.agents.values()) {
      if (a.specRef === specRef && agentStateIsActive(a.state)) {
        agentId = a.agentId
        break
      }
    }
    const locked = this.lockedBranches.has(specRef)
    const hasQuestion = this.pendingQuestions.some((q) => q.questionNodeRef === specRef)

    out.push({
      kind: 'node',
      id: node.id,
      depth,
      markdown: node.markdown,
      selected: isSelected,
      selectionHighlighted,
      collapsed: node.collapsed,
      hasChildren: node.children.length > 0,
      codeRefs: node.codeRefs,
      verification: node.verification,
      dependsOn: node.dependsOn,
      relatedTo: node.relatedTo,
      agentId,
      locked,
      hasQuestion,
    })

    if (!node.collapsed) {
      // Emit code_ref sub-rows right below the node, before its children.
      for (let ri = 0; ri < node.codeRefs.length; ri++) {
        out.push({
          kind: 'codeRef',
          // Synthetic ID (negative) so it never collides with real node IDs.
          id: -(node.id * 1000 + ri + 1),
          depth: depth + 1,
          markdown: '',
          selected: false,
          selectionHighlighted: false,
          collapsed: false,
          hasChildren: false,
          codeRefs: [],
          verification: null,
          dependsOn: [],
          relatedTo: [],
          agentId: null,
          locked: false,
          hasQuestion: false,
          codeRefValue: node.codeRefs[ri],
          codeRefIndex: ri,
          parentNodeId: node.id,
        })
      }

      for (const childId of node.children) {
        this._collectFlat(childId, depth + 1, selectionHighlighted, out)
      }
    }
  }
}

// ─── Singleton export ─────────────────────────────────────────────────────────

export const appState: AppState = import.meta.hot?.data?.appState ?? new AppState()
if (import.meta.hot) {
  import.meta.hot.data ??= {}
  import.meta.hot.data.appState = appState
}

// Re-export for convenience
export type { AppState }
export { agentStateFromString, agentStateIsActive }

// ─── Test helpers (used by Vitest, no-op in production) ───────────────────────

/**
 * Reset the singleton appState to a blank slate.
 * Call this in `beforeEach` in tests.
 */
export function resetAppState(): void {
  appState.nodes = []
  appState.rootNodes = []
  appState.specRefIndex = new Map()
  appState.selectedNode = null
  appState.selectedSpecRef = null
  appState.editorMode = 'normal'
  appState.chatDraft = ''
  appState.connectionState = 'offline'
  appState.agents = new Map()
  appState.lockedBranches = new Set()
  appState.pendingQuestions = []
  appState.detailEvents = new Map()
  appState.detailAgentId = null
  appState.primeMessages = []
  appState.primeStreaming = false
  appState.primeStreamBuffer = ''
  appState.primeChatEntries = []
  appState.primeToolCalls = new Map()
  appState.primeSubAgents = new Map()
  appState.primeHistoryHasMore = false
  appState.primeOldestSeq = null
  appState.primeHistoryLoading = false
  appState.primeReplyTo = null
  appState.launchTier = 'medium'
  appState.metadataEditTarget = null
  appState.runState = { status: 'idle', runId: null, specRef: null, command: null, exitCode: null, lines: [] }
}

/**
 * Load a small demo tree into the singleton appState.
 * Mirrors AppState::demo() in the Rust implementation.
 *
 * Tree:
 *   root (depth 0)
 *     Spec Tree Pane (depth 1)
 *       Editable Nodes (depth 2)
 *       Tab Indent (depth 2)
 *     Chat Pane (depth 1)
 */
export function loadDemoState(): void {
  resetAppState()
  appState.hydrateFromBackend([
    { id: '0', spec_ref: 'specs/_main.md', depth: 0, markdown: 'root' },
    { id: '1', spec_ref: 'specs/_main.md#spec-tree-pane', depth: 1, markdown: 'Spec Tree Pane' },
    { id: '2', spec_ref: 'specs/_main.md#editable-nodes', depth: 2, markdown: 'Editable Nodes' },
    { id: '3', spec_ref: 'specs/_main.md#tab-indent', depth: 2, markdown: 'Tab Indent' },
    { id: '4', spec_ref: 'specs/_main.md#chat-pane', depth: 1, markdown: 'Chat Pane' },
  ])
  // Expand everything for tests
  for (const node of appState.nodes) {
    node.collapsed = false
  }
  appState.connectionState = 'ready'
}
