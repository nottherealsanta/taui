/**
 * 9.3 WebSocket client tests.
 * Mocks the browser WebSocket API to test JSON-RPC request/response,
 * notification routing, and reconnection logic.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { BackendClient } from './backend-client'
import type { ServerNotification } from './backend-client'

// ── Mock WebSocket ────────────────────────────────────────────────────────────

class MockWebSocket {
  static instances: MockWebSocket[] = []

  readyState: number = 0 // CONNECTING
  url: string
  sentMessages: string[] = []

  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSING = 2
  readonly CLOSED = 3

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sentMessages.push(data)
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  /** Test helper: simulate connection open */
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  /** Test helper: simulate a message from the server */
  simulateMessage(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  /** Test helper: simulate server closing */
  simulateClose() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }
}

// Install mock before each test, restore after
beforeEach(() => {
  MockWebSocket.instances = []
  vi.stubGlobal('WebSocket', MockWebSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function latestSocket(): MockWebSocket {
  const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
  if (!ws) throw new Error('No MockWebSocket created')
  return ws
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('BackendClient construction', () => {
  it('uses default endpoint when none provided', () => {
    const client = new BackendClient()
    client.connect()
    expect(latestSocket().url).toContain('ws://')
  })

  it('uses custom endpoint when provided', () => {
    const client = new BackendClient('ws://custom:9999/ws')
    client.connect()
    expect(latestSocket().url).toBe('ws://custom:9999/ws')
  })
})

describe('connection lifecycle', () => {
  it('emits connectionState=open on WebSocket open', () => {
    const client = new BackendClient()
    const states: string[] = []
    client.addEventListener('connectionState', (e) => {
      states.push((e as CustomEvent<string>).detail)
    })

    client.connect()
    latestSocket().simulateOpen()

    expect(states).toContain('open')
  })

  it('emits connectionState=closed on WebSocket close', () => {
    const client = new BackendClient()
    const states: string[] = []
    client.addEventListener('connectionState', (e) => {
      states.push((e as CustomEvent<string>).detail)
    })

    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()
    ws.simulateClose()

    expect(states).toContain('closed')
  })

  it('destroy() stops reconnection and rejects pending calls', async () => {
    const client = new BackendClient()
    client.connect()
    latestSocket().simulateOpen()

    const callPromise = client.runStatus()
    client.destroy()

    await expect(callPromise).rejects.toThrow()
  })
})

describe('JSON-RPC request/response', () => {
  it('sends a well-formed JSON-RPC request', async () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    const pending = client.runStatus()

    expect(ws.sentMessages.length).toBe(1)
    const req = JSON.parse(ws.sentMessages[0])
    expect(req.jsonrpc).toBe('2.0')
    expect(req.method).toBe('run/status')
    expect(typeof req.id).toBe('number')

    // Simulate success response
    ws.simulateMessage({ jsonrpc: '2.0', id: req.id, result: { status: 'idle' } })
    const result = await pending
    expect(result).toEqual({ status: 'idle' })
  })

  it('increments request ids for each call', async () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    // Fire two calls without awaiting
    const p1 = client.runStatus()
    const p2 = client.runStatus()

    const req1 = JSON.parse(ws.sentMessages[0])
    const req2 = JSON.parse(ws.sentMessages[1])

    expect(req1.id).not.toBe(req2.id)

    // Resolve both
    ws.simulateMessage({ jsonrpc: '2.0', id: req1.id, result: { status: 'idle' } })
    ws.simulateMessage({ jsonrpc: '2.0', id: req2.id, result: { status: 'idle' } })

    await Promise.all([p1, p2])
  })

  it('rejects when the server returns an RPC error', async () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    const pending = client.runStatus()
    const req = JSON.parse(ws.sentMessages[0])

    ws.simulateMessage({
      jsonrpc: '2.0',
      id: req.id,
      error: { code: -32601, message: 'Method not found' },
    })

    await expect(pending).rejects.toThrow('Method not found')
  })

  it('rejects pending calls when socket closes', async () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    const pending = client.runStatus()
    ws.simulateClose()

    await expect(pending).rejects.toBeDefined()
  })

  it('rejects immediately when not connected', async () => {
    const client = new BackendClient()
    // Do NOT call connect() — socket never opened

    const pending = client.runStatus()
    await expect(pending).rejects.toThrow('not connected')
  })
})

describe('server notifications', () => {
  it('emits notification event for server-sent messages', () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    const received: ServerNotification[] = []
    client.addEventListener('notification', (e) => {
      received.push((e as CustomEvent<ServerNotification>).detail)
    })

    ws.simulateMessage({
      jsonrpc: '2.0',
      method: 'spec/nodeChanged',
      params: { node: { spec_ref: 'specs/_main.md', markdown: 'updated' } },
    })

    expect(received).toHaveLength(1)
    expect(received[0].method).toBe('spec/nodeChanged')
  })

  it('does not emit notification event for responses', () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    const notifSpy = vi.fn()
    client.addEventListener('notification', notifSpy)

    // Call and immediately resolve
    const p = client.runStatus()
    const req = JSON.parse(ws.sentMessages[0])
    ws.simulateMessage({ jsonrpc: '2.0', id: req.id, result: { status: 'idle' } })

    expect(notifSpy).not.toHaveBeenCalled()
    return p
  })

  it('ignores unparseable messages silently', () => {
    const client = new BackendClient()
    client.connect()
    const ws = latestSocket()
    ws.simulateOpen()

    // Should not throw
    expect(() => ws.onmessage?.({ data: 'not valid json {{{' })).not.toThrow()
  })
})
