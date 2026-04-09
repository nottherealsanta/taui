/**
 * Durable Streams HTTP client for the Taui frontend.
 *
 * Provides offset-based resumable reading from durable streams exposed
 * by the backend at `/streams/{stream_id}`.
 *
 * ## Usage
 *
 * ### Catch-up read (one-shot):
 * ```ts
 * const events = await streamClient.read('agents/abc-123', { offset: 0 })
 * ```
 *
 * ### Live-tail via SSE:
 * ```ts
 * const aborter = new AbortController()
 * for await (const event of streamClient.tail('agents/abc-123', { offset: 0, signal: aborter.signal })) {
 *   console.log(event.offset, event.data)
 * }
 * ```
 *
 * ### Offset tracking:
 * Consumers store `lastOffset` in a Svelte store or localStorage and resume
 * from that offset on reconnect — no events are ever missed.
 */

// ── Types ────────────────────────────────────────────────────────────────────

export interface StreamChunk {
  offset: number
  data: unknown
}

export interface ReadOptions {
  offset?: number
  limit?: number
}

export interface TailOptions {
  offset?: number
  signal?: AbortSignal
}

export interface StreamInfo {
  length: number
  closed: boolean
}

// ── Client ───────────────────────────────────────────────────────────────────

export class StreamClient {
  private readonly baseUrl: string

  constructor(baseUrl?: string) {
    // Derive from the WebSocket endpoint or use default
    const wsEndpoint =
      typeof import.meta !== 'undefined' && import.meta.env?.VITE_TAUI_BACKEND_WS
    const httpBase = wsEndpoint
      ? wsEndpoint.replace(/^ws/, 'http').replace(/\/ws\/?$/, '')
      : 'http://127.0.0.1:8000'
    this.baseUrl = baseUrl ?? `${httpBase}/streams`
  }

  // ── Stream info ──────────────────────────────────────────────────────────

  async info(streamId: string): Promise<StreamInfo | null> {
    const resp = await fetch(`${this.baseUrl}/${streamId}`, { method: 'HEAD' })
    if (resp.status === 404) return null
    return {
      length: parseInt(resp.headers.get('Stream-Length') ?? '0', 10),
      closed: resp.headers.get('Stream-Closed') === 'true',
    }
  }

  // ── Catch-up read ────────────────────────────────────────────────────────

  /**
   * One-shot read of chunks from a stream.
   * Returns an array of chunks starting from the given offset.
   */
  async read(streamId: string, opts: ReadOptions = {}): Promise<StreamChunk[]> {
    const { offset = 0, limit = 1000 } = opts
    const url = new URL(`${this.baseUrl}/${streamId}`)
    url.searchParams.set('offset', String(offset))
    url.searchParams.set('limit', String(limit))

    const resp = await fetch(url.toString())
    if (resp.status === 404) return []
    if (!resp.ok) throw new Error(`Stream read failed: ${resp.status} ${resp.statusText}`)

    const text = await resp.text()
    if (!text.trim()) return []

    const chunks: StreamChunk[] = []
    for (const line of text.trim().split('\n')) {
      if (!line) continue
      try {
        chunks.push(JSON.parse(line) as StreamChunk)
      } catch {
        console.warn('[stream] Failed to parse chunk line:', line)
      }
    }
    return chunks
  }

  // ── Live-tail via SSE ────────────────────────────────────────────────────

  /**
   * Async generator that yields chunks as they arrive via Server-Sent Events.
   *
   * Starts from the given offset and yields all existing chunks (catch-up),
   * then continues yielding as new chunks are appended.
   *
   * Terminates when the stream is closed (EOF event), the signal is aborted,
   * or the connection drops.
   */
  async *tail(streamId: string, opts: TailOptions = {}): AsyncGenerator<StreamChunk> {
    const { offset = 0, signal } = opts
    const url = new URL(`${this.baseUrl}/${streamId}`)
    url.searchParams.set('offset', String(offset))
    url.searchParams.set('live', 'sse')

    const resp = await fetch(url.toString(), { signal })
    if (!resp.ok) throw new Error(`Stream tail failed: ${resp.status}`)
    if (!resp.body) throw new Error('Stream tail: no response body')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        if (signal?.aborted) return

        const { done, value } = await reader.read()
        if (done) return

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6)
            try {
              yield JSON.parse(payload) as StreamChunk
            } catch {
              console.warn('[stream] Failed to parse SSE data:', payload)
            }
          } else if (line.startsWith('event: eof')) {
            // Stream closed — stop tailing
            return
          } else if (line.startsWith('event: error')) {
            console.error('[stream] Server error event')
            return
          }
          // Skip keepalive comments (lines starting with ':')
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  // ── Long-poll read ───────────────────────────────────────────────────────

  /**
   * Long-poll read: blocks until new data is available at the given offset,
   * then returns the available chunks. Returns empty array on timeout (304).
   */
  async longPoll(streamId: string, opts: ReadOptions = {}): Promise<StreamChunk[]> {
    const { offset = 0, limit = 1000 } = opts
    const url = new URL(`${this.baseUrl}/${streamId}`)
    url.searchParams.set('offset', String(offset))
    url.searchParams.set('limit', String(limit))
    url.searchParams.set('live', 'long-poll')

    const resp = await fetch(url.toString())
    if (resp.status === 304) return [] // Timeout, no new data
    if (resp.status === 404) return []
    if (!resp.ok) throw new Error(`Stream long-poll failed: ${resp.status}`)

    const text = await resp.text()
    if (!text.trim()) return []

    const chunks: StreamChunk[] = []
    for (const line of text.trim().split('\n')) {
      if (!line) continue
      try {
        chunks.push(JSON.parse(line) as StreamChunk)
      } catch {
        console.warn('[stream] Failed to parse chunk line:', line)
      }
    }
    return chunks
  }
}

// ── Singleton instance ───────────────────────────────────────────────────────

export const streamClient = new StreamClient()

// ── Convenience helpers ──────────────────────────────────────────────────────

/**
 * Read all agent events from a durable stream.
 * Returns events with their offsets for resumability.
 */
export async function readAgentEvents(
  agentId: string,
  opts: ReadOptions = {},
): Promise<StreamChunk[]> {
  return streamClient.read(`agents/${agentId}`, opts)
}

/**
 * Tail agent events as an async generator.
 * Yields chunks as they arrive via SSE.
 */
export async function* tailAgentEvents(
  agentId: string,
  opts: TailOptions = {},
): AsyncGenerator<StreamChunk> {
  yield* streamClient.tail(`agents/${agentId}`, opts)
}

/**
 * Read Prime token events from the durable stream.
 */
export async function readPrimeTokens(
  opts: ReadOptions = {},
): Promise<StreamChunk[]> {
  return streamClient.read('prime/tokens', opts)
}

/**
 * Tail Prime token events as an async generator.
 */
export async function* tailPrimeTokens(
  opts: TailOptions = {},
): AsyncGenerator<StreamChunk> {
  yield* streamClient.tail('prime/tokens', opts)
}

/**
 * Read Prime events (tool calls, results, state changes) from the durable stream.
 */
export async function readPrimeEvents(
  opts: ReadOptions = {},
): Promise<StreamChunk[]> {
  return streamClient.read('prime', opts)
}
