/**
 * JSON-RPC 2.0 WebSocket client for the Taui Python backend.
 * Ported from ui/src/services/backend_client.rs with TypeScript idioms.
 *
 * • Auto-reconnects with exponential backoff (250ms → 30s).
 * • In-flight requests are correlated by id; responses are routed via Promises.
 * • Server-initiated notifications are emitted via an EventTarget.
 */

import type {
  BackendInitializeResponse,
  BackendTreeResponse,
  BackendUpdateNodeResponse,
  CodeRefsResponse,
  CodeRefPreview,
  SourceRangeResponse,
  BackendRunState,
  FileEntry,
  SearchResult,
} from '$types/index'
import { toasts } from '$stores/toasts.svelte'

// ─── JSON-RPC wire types ──────────────────────────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: '2.0'
  id: number
  method: string
  params: unknown
}

interface JsonRpcResponse {
  jsonrpc: string
  id?: number
  result?: unknown
  error?: { code: number; message: string; data?: unknown }
  method?: string
  params?: unknown
}

// ─── Server notifications ─────────────────────────────────────────────────────

export interface ServerNotification {
  method: string
  params: unknown
}

/** CustomEvent detail type for notifications. */
export type NotificationEvent = CustomEvent<ServerNotification>

// ─── Client ───────────────────────────────────────────────────────────────────

export class BackendClient extends EventTarget {
  readonly endpoint: string

  private nextId = 1
  private ws: WebSocket | null = null
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private backoffMs = 250
  private destroyed = false

  constructor(endpoint?: string) {
    super()
    this.endpoint = endpoint ?? import.meta.env.VITE_TAUI_BACKEND_WS ?? 'ws://127.0.0.1:8000/ws'
  }

  // ── Connection management ──────────────────────────────────────────────────

  /** Open the WebSocket. Call once on app mount. */
  connect(): void {
    if (this.destroyed) return
    this._openSocket()
  }

  /** Close and stop all reconnection attempts. */
  destroy(): void {
    this.destroyed = true
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this._rejectAllPending(new Error('BackendClient destroyed'))
  }

  private _openSocket(): void {
    if (this.destroyed) return

    this._emitConnectionState('connecting')

    let ws: WebSocket
    try {
      ws = new WebSocket(this.endpoint)
    } catch (e) {
      this._scheduleReconnect()
      return
    }

    ws.onopen = () => {
      this.backoffMs = 250
      this._emitConnectionState('open')
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      this._handleMessage(ev.data)
    }

    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null
        this._emitConnectionState('closed')
        this._rejectAllPending(new Error('WebSocket closed'))
        this._scheduleReconnect()
      }
    }

    ws.onerror = () => {
      // onclose fires right after, so no extra handling needed.
    }

    this.ws = ws
  }

  private _scheduleReconnect(): void {
    if (this.destroyed) return
    const delay = this.backoffMs
    this.backoffMs = Math.min(this.backoffMs * 2, 30_000)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this._openSocket()
    }, delay)
  }

  private _handleMessage(text: string): void {
    let msg: JsonRpcResponse
    try {
      msg = JSON.parse(text) as JsonRpcResponse
    } catch {
      return
    }

    if (typeof msg.id === 'number') {
      // Response to an outstanding request.
      const pending = this.pending.get(msg.id)
      if (pending) {
        this.pending.delete(msg.id)
        if (msg.error) {
          const err = new Error(`RPC ${msg.error.code}: ${msg.error.message}`)
          toasts.error(`${msg.error.message}`)
          pending.reject(err)
        } else {
          pending.resolve(msg.result)
        }
      }
    } else if (msg.method) {
      // Server-initiated notification.
      const notification: ServerNotification = { method: msg.method, params: msg.params ?? null }
      this.dispatchEvent(new CustomEvent<ServerNotification>('notification', { detail: notification }))
    }
  }

  private _rejectAllPending(err: Error): void {
    for (const { reject } of this.pending.values()) {
      reject(err)
    }
    this.pending.clear()
  }

  private _emitConnectionState(state: 'connecting' | 'open' | 'closed'): void {
    this.dispatchEvent(new CustomEvent('connectionState', { detail: state }))
  }

  // ── RPC core ──────────────────────────────────────────────────────────────

  private call(method: string, params: unknown = {}): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error(`BackendClient: not connected (calling ${method})`))
        return
      }
      const id = this.nextId++
      this.pending.set(id, { resolve, reject })
      const req: JsonRpcRequest = { jsonrpc: '2.0', id, method, params }
      try {
        this.ws.send(JSON.stringify(req))
      } catch (e) {
        this.pending.delete(id)
        reject(e)
      }
    })
  }

  // ── Public RPC methods ────────────────────────────────────────────────────

  async initialize(workspace?: string): Promise<BackendInitializeResponse> {
    const params: Record<string, unknown> = {}
    if (workspace) params['workspace'] = workspace
    return this.call('initialize', params) as Promise<BackendInitializeResponse>
  }

  async getTreeDetailed(): Promise<BackendTreeResponse> {
    return this.call('spec/getTreeDetailed', {}) as Promise<BackendTreeResponse>
  }

  async updateNode(specRef: string, markdown: string): Promise<BackendUpdateNodeResponse> {
    return this.call('spec/updateNode', {
      spec_ref: specRef,
      patch: { markdown },
    }) as Promise<BackendUpdateNodeResponse>
  }

  async createSiblingNode(specRef: string): Promise<BackendUpdateNodeResponse> {
    return this.call('spec/createSiblingNode', { spec_ref: specRef }) as Promise<BackendUpdateNodeResponse>
  }

  async indentNode(specRef: string): Promise<void> {
    await this.call('spec/indentNode', { spec_ref: specRef })
  }

  async outdentNode(specRef: string): Promise<void> {
    await this.call('spec/outdentNode', { spec_ref: specRef })
  }

  async getNodeCodeRefs(specRef: string, maxLines?: number): Promise<CodeRefsResponse> {
    const params: Record<string, unknown> = { spec_ref: specRef }
    if (maxLines !== undefined) params['max_lines'] = maxLines
    const raw = await this.call('spec/getNodeCodeRefs', params) as {
      refs: Array<{
        raw_ref: string
        file_path: string
        line_start?: number | null
        line_end?: number | null
        preview_start?: number | null
        preview_end?: number | null
        content: string
        truncated: boolean
        error?: string | null
      }>
    }
    return {
      refs: raw.refs.map((r): CodeRefPreview => ({
        rawRef: r.raw_ref,
        filePath: r.file_path,
        lineStart: r.line_start ?? null,
        lineEnd: r.line_end ?? null,
        previewStart: r.preview_start ?? null,
        previewEnd: r.preview_end ?? null,
        content: r.content,
        truncated: r.truncated,
        error: r.error ?? null,
      })),
    }
  }

  // ── Spec source range ─────────────────────────────────────────────────────

  async getNodeSourceRange(
    specRef: string,
    opts?: { expanded?: boolean; maxLines?: number }
  ): Promise<SourceRangeResponse> {
    const params: Record<string, unknown> = { spec_ref: specRef }
    if (opts?.expanded !== undefined) params['expanded'] = opts.expanded
    if (opts?.maxLines !== undefined) params['max_lines'] = opts.maxLines
    return this.call('spec/getNodeSourceRange', params) as Promise<SourceRangeResponse>
  }

  // ── Run RPCs ──────────────────────────────────────────────────────────────

  async runStart(specRef: string, command: string, workdir?: string): Promise<BackendRunState> {
    const params: Record<string, unknown> = { spec_ref: specRef, command }
    if (workdir) params['workdir'] = workdir
    return this.call('run/start', params) as Promise<BackendRunState>
  }

  async runStop(): Promise<BackendRunState> {
    return this.call('run/stop', {}) as Promise<BackendRunState>
  }

  async runStatus(): Promise<BackendRunState> {
    return this.call('run/status', {}) as Promise<BackendRunState>
  }

  // ── Agent RPCs ────────────────────────────────────────────────────────────

  async agentLaunch(specRef: string, task: string, tier: string): Promise<{ agentId: string; sessionId: string }> {
    const result = await this.call('agent/launch', { spec_ref: specRef, task, tier }) as { agent_id: string; session_id: string }
    return { agentId: result.agent_id, sessionId: result.session_id }
  }

  async agentStop(agentId: string): Promise<void> {
    await this.call('agent/stop', { agent_id: agentId })
  }

  async agentSteer(agentId: string, message: string): Promise<void> {
    await this.call('agent/steer', { agent_id: agentId, message })
  }

  async agentQueue(agentId: string, message: string): Promise<void> {
    await this.call('agent/queue', { agent_id: agentId, message })
  }

  async agentSubscribe(agentId: string): Promise<unknown[]> {
    const result = await this.call('agent/subscribe', { agent_id: agentId }) as { backlog: unknown[] }
    return result.backlog ?? []
  }

  async agentUnsubscribe(agentId: string): Promise<void> {
    await this.call('agent/unsubscribe', { agent_id: agentId })
  }

  async agentAnswerQuestion(agentId: string, answer: string): Promise<void> {
    await this.call('agent/answerQuestion', { agent_id: agentId, answer })
  }

  // ── Prime RPCs ─────────────────────────────────────────────────────────────

  async primeMessage(messages: Array<{ role: string; content: string }>): Promise<{ ok: boolean }> {
    return this.call('prime/message', { messages }) as Promise<{ ok: boolean }>
  }

  async primeHistory(): Promise<{ messages: Array<{ role: string; content: string }> }> {
    return this.call('prime/history', {}) as Promise<{ messages: Array<{ role: string; content: string }> }>
  }

  async primeCancel(): Promise<{ ok: boolean }> {
    return this.call('prime/cancel', {}) as Promise<{ ok: boolean }>
  }

  async primeNewContext(seed?: string): Promise<{ ok: boolean; unsupported?: boolean }> {
    const params: Record<string, unknown> = {}
    if (seed && seed.trim()) params['seed'] = seed.trim()
    try {
      return await this.call('prime/newContext', params) as Promise<{ ok: boolean }>
    } catch (e) {
      const msg = String(e)
      // Backward compatibility for older backends that don't expose prime/newContext.
      if (msg.includes('RPC -32601')) {
        return { ok: false, unsupported: true }
      }
      throw e
    }
  }

  async agentList(): Promise<{ agents: Array<{ agent_id: string; spec_ref: string; state: string; agent_type: string; display_name: string; tier: string }> }> {
    return this.call('agent/list', {}) as Promise<{ agents: Array<{ agent_id: string; spec_ref: string; state: string; agent_type: string; display_name: string; tier: string }> }>
  }

  // ── Filesystem RPCs ───────────────────────────────────────────────────────

  async listDir(path: string): Promise<{ entries: FileEntry[] }> {
    const raw = await this.call('fs/listDir', { path }) as {
      entries: Array<{ name: string; path: string; is_dir: boolean; extension: string }>
    }
    return {
      entries: raw.entries.map((e): FileEntry => ({
        name: e.name,
        path: e.path,
        isDir: e.is_dir,
        extension: e.extension,
      })),
    }
  }

  async readFile(path: string): Promise<{ content: string; frontmatter?: Record<string, unknown> }> {
    return this.call('fs/readFile', { path }) as Promise<{ content: string; frontmatter?: Record<string, unknown> }>
  }

  async writeFile(path: string, content: string): Promise<void> {
    await this.call('fs/writeFile', { path, content })
  }

  async createDir(path: string): Promise<void> {
    await this.call('fs/createDir', { path })
  }

  async searchFiles(query: string, opts?: { regex?: boolean; caseSensitive?: boolean; filePattern?: string }): Promise<{ results: SearchResult[] }> {
    const params: Record<string, unknown> = { query }
    if (opts?.regex !== undefined) params['regex'] = opts.regex
    if (opts?.caseSensitive !== undefined) params['case_sensitive'] = opts.caseSensitive
    if (opts?.filePattern !== undefined) params['file_pattern'] = opts.filePattern
    const raw = await this.call('fs/search', params) as {
      results: Array<{
        file_path: string
        line_number: number
        line_content: string
        match_start: number
        match_end: number
      }>
    }
    return {
      results: raw.results.map((r): SearchResult => ({
        filePath: r.file_path,
        lineNumber: r.line_number,
        lineContent: r.line_content,
        matchStart: r.match_start,
        matchEnd: r.match_end,
      })),
    }
  }

  async getBacklinks(filePath: string): Promise<{ backlinks: Array<{ filePath: string; lineNumber: number; context: string }> }> {
    return this.call('spec/getBacklinks', { file_path: filePath }) as Promise<{ backlinks: Array<{ filePath: string; lineNumber: number; context: string }> }>
  }
}

// ─── Singleton ────────────────────────────────────────────────────────────────

export const backendClient: BackendClient = import.meta.hot?.data?.backendClient ?? new BackendClient()
if (import.meta.hot) {
  import.meta.hot.data.backendClient = backendClient
}
