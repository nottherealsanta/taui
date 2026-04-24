/**
 * Mock WebSocket backend for Playwright E2E tests.
 *
 * Simulates the Taui Python backend's JSON-RPC 2.0 protocol over WebSocket.
 * Starts a real WS server on a given port and responds to RPC methods that
 * the frontend calls during initialization and normal usage.
 */
import { WebSocketServer, WebSocket } from 'ws'
import type { AddressInfo } from 'net'

export interface MockBackendOptions {
  port?: number
  projectTitle?: string
  model?: string
  nodes?: BackendNode[]
}

export interface BackendNode {
  id: string
  spec_ref?: string
  tangle_ref?: string
  depth: number
  markdown: string
  status?: string | null
  code_refs?: string[]
  verification?: string | null
  depends_on?: string[]
  related_to?: string[]
}

interface JsonRpcRequest {
  jsonrpc: string
  id: number
  method: string
  params: Record<string, unknown>
}

const DEFAULT_NODES: BackendNode[] = [
  { id: '0', tangle_ref: 'specs/index.md', depth: 0, markdown: '# My Project' },
  { id: '1', tangle_ref: 'specs/index.md#overview', depth: 1, markdown: '## Overview' },
  { id: '2', tangle_ref: 'specs/index.md#architecture', depth: 1, markdown: '## Architecture' },
  { id: '3', tangle_ref: 'specs/index.md#components', depth: 2, markdown: '### Components' },
  { id: '4', tangle_ref: 'specs/index.md#api', depth: 1, markdown: '## API' },
    {
      id: '5',
      tangle_ref: 'specs/design.md',
      depth: 0,
      markdown: '# Design System\n\n- Inline reference `src/lib/sample.ts:renderChip` should render as a boxed code ref.\n- Missing reference `src/lib/missing.ts:missingThing` should show no preview available.\n\nsrc/lib/standalone.ts:10-24',
    },
   { id: '6', tangle_ref: 'specs/design.md#colors', depth: 1, markdown: '## Colors' },
]

const FILE_CONTENTS: Record<string, { content: string; frontmatter?: Record<string, unknown> }> = {
  'specs/index.md': {
    content: '# My Project\n\n## Overview\n\nA test project.',
    frontmatter: {},
  },
  'specs/design.md': {
    content: `# Design System

- Inline reference \`src/lib/sample.ts:renderChip\` should render as a boxed code ref.
- Missing reference \`src/lib/missing.ts:missingThing\` should show no preview available.

src/lib/standalone.ts:10-24
`,
    frontmatter: {},
  },
  'src/lib/sample.ts': {
    content: [
      'export function renderChip(label: string): string {',
      '  const safe = label.trim()',
      "  const prefix = '[code-ref]'",
      '  if (!safe) return prefix',
      '  return `${prefix} ${safe}`',
      '}',
      '',
      'export function secondaryHelper(value: string): string {',
      '  return value.toUpperCase()',
      '}',
      '',
    ].join('\n'),
  },
  'src/lib/standalone.ts': {
    content: [
      "const palette = ['blue', 'cyan', 'violet']",
      '',
      'export function firstColor(): string {',
      '  return palette[0]',
      '}',
      '',
      'export function lastColor(): string {',
      '  return palette[palette.length - 1]',
      '}',
      '',
      'export function renderStandalonePreview(): string {',
      "  const preview = palette.map((item, index) => `${index}:${item}`).join(', ')",
      '  return `standalone ${preview}`',
      '}',
      '',
      'export function endMarker(): string {',
      "  return 'done'",
      '}',
      '',
    ].join('\n'),
  },
}

function resolveCodeRef(filePath: string, target: string, refKind: string) {
  if (filePath === 'src/lib/sample.ts' && target === 'renderChip' && refKind === 'symbol') {
    return {
      file_path: filePath,
      target,
      ref_kind: refKind,
      resolved_start: 1,
      resolved_end: 6,
      content: `export function renderChip(label: string): string {
  const safe = label.trim()
  const prefix = '[code-ref]'
  if (!safe) return prefix
  return \`${'${prefix} ${safe}'}\`
}`,
      language: 'typescript',
      diagnostic: 'resolved',
      symbol_kind: 'function',
      symbol_metadata: {},
    }
  }

  if (filePath === 'src/lib/standalone.ts' && target === '10-24' && refKind === 'lines') {
    return {
      file_path: filePath,
      target,
      ref_kind: refKind,
      resolved_start: 10,
      resolved_end: 17,
      content: `export function renderStandalonePreview(): string {
  const preview = palette.map((item, index) => \`${'${index}:${item}'}\`).join(', ')
  return \`standalone ${'${preview}'}\`
}

export function endMarker(): string {
  return 'done'
}`,
      language: 'typescript',
      diagnostic: 'resolved',
    }
  }

  return {
    file_path: filePath,
    target,
    ref_kind: refKind,
    resolved_start: null,
    resolved_end: null,
    content: null,
    language: filePath.endsWith('.ts') ? 'typescript' : 'plaintext',
    diagnostic: 'unresolved',
    error: 'Reference not found',
  }
}

export class MockBackend {
  private wss: WebSocketServer | null = null
  private clients: Set<WebSocket> = new Set()
  private opts: Required<MockBackendOptions>

  /** Recorded RPC calls for assertions */
  public rpcCalls: Array<{ method: string; params: unknown }> = []

  constructor(opts: MockBackendOptions = {}) {
    this.opts = {
      port: opts.port ?? 8000,
      projectTitle: opts.projectTitle ?? 'Test Project',
      model: opts.model ?? 'copilot:claude-sonnet-4.6',
      nodes: opts.nodes ?? DEFAULT_NODES,
    }
  }

  async start(): Promise<number> {
    return new Promise((resolve, reject) => {
      this.wss = new WebSocketServer({ port: this.opts.port, path: '/ws' })

      this.wss.on('listening', () => {
        const addr = this.wss!.address() as AddressInfo
        resolve(addr.port)
      })

      this.wss.on('error', reject)

      this.wss.on('connection', (ws) => {
        this.clients.add(ws)
        ws.on('close', () => this.clients.delete(ws))
        ws.on('message', (data) => {
          try {
            const msg = JSON.parse(data.toString()) as JsonRpcRequest
            this.rpcCalls.push({ method: msg.method, params: msg.params })
            const result = this.handleRpc(msg)
            if (result !== undefined) {
              ws.send(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result }))
            }
          } catch (err) {
            console.error('[MockBackend] message error:', err)
          }
        })
      })
    })
  }

  async stop(): Promise<void> {
    for (const client of this.clients) {
      client.close()
    }
    this.clients.clear()

    return new Promise((resolve) => {
      if (!this.wss) {
        resolve()
        return
      }
      this.wss.close(() => {
        this.wss = null
        resolve()
      })
    })
  }

  /** Send a JSON-RPC notification to all connected clients. */
  notify(method: string, params: unknown): void {
    const msg = JSON.stringify({ jsonrpc: '2.0', method, params })
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(msg)
      }
    }
  }

  private handleRpc(msg: JsonRpcRequest): unknown {
    switch (msg.method) {
      case 'initialize':
        return {
          protocolVersion: '1.0',
          serverName: 'taui-mock',
          workspace: '/mock/workspace',
          projectTitle: this.opts.projectTitle,
          capabilities: {},
          model: this.opts.model,
        }

      case 'ui/snapshot':
        return {
          tangleTree: this.opts.nodes,
          tabs: { open: [], active: '' },
          layout: { sidebarCollapsed: false },
          theme: null,
        }

      case 'tangle/getTreeDetailed':
        return { nodes: this.opts.nodes }

      case 'prime/history':
        return { messages: [], has_more: false, oldest_seq: null }

      case 'agent/list':
        return { agents: [] }

      case 'tangle/updateNode':
        return {
          previous_spec_ref: msg.params.tangle_ref,
          node: this.opts.nodes[0] ?? {},
          tree_changed: false,
        }

      case 'tangle/createSiblingNode':
        return {
          previous_spec_ref: msg.params.tangle_ref,
          node: {
            id: '99',
            tangle_ref: 'specs/index.md#new-node',
            depth: 1,
            markdown: '## New Node',
          },
          tree_changed: true,
        }

      case 'tangle/indentNode':
      case 'tangle/outdentNode':
        return {}

      case 'tangle/getNodeCodeRefs':
        return { refs: [] }

      case 'tangle/getNodeSourceRange':
        return {
          file_path: 'specs/index.md',
          line_start: 1,
          line_end: 10,
          preview_start: 1,
          preview_end: 10,
          content: '# Test content',
          truncated: false,
        }

      case 'tangle/getBacklinks':
        return { backlinks: [] }

      case 'fs/listDir':
        return {
          entries: [
            { name: 'index.md', path: 'specs/index.md', is_dir: false, extension: '.md' },
            { name: 'design.md', path: 'specs/design.md', is_dir: false, extension: '.md' },
          ],
        }

      case 'fs/readFile':
        return FILE_CONTENTS[String(msg.params.path)] ?? { content: '# Mock File Content\n\nSome text here.', frontmatter: {} }

      case 'code/resolve':
        return resolveCodeRef(
          String(msg.params.file_path ?? ''),
          String(msg.params.target ?? ''),
          String(msg.params.ref_kind ?? 'symbol'),
        )

      case 'fs/writeFile':
      case 'fs/createDir':
        return {}

      case 'fs/search':
        return { results: [] }

      case 'prime/message':
        // Simulate a streaming response
        setTimeout(() => {
          this.notify('prime/token', { text: 'Hello! ' })
          this.notify('prime/token', { text: 'I am Prime.' })
          this.notify('prime/done', {})
        }, 100)
        return { ok: true }

      case 'prime/cancel':
        return { ok: true }

      case 'prime/newContext':
        return { ok: true }

      case 'agent/launch': {
        const agentId = `agent-${Date.now()}`
        // Emit prime/agentLaunched notification so the UI creates a tab
        setTimeout(() => {
          this.notify('prime/agentLaunched', {
            agent_id: agentId,
            display_name: (msg.params.task as string)?.slice(0, 20) || 'Root Agent',
            task: msg.params.task ?? '',
            tangle_ref: msg.params.tangle_ref ?? '',
          })
        }, 50)
        return { agent_id: agentId, session_id: `session-${Date.now()}` }
      }

      case 'agent/stop':
      case 'agent/steer':
      case 'agent/queue':
      case 'agent/answerQuestion':
        return {}

      case 'agent/subscribe':
        return { backlog: [] }

      case 'agent/unsubscribe':
        return {}

      case 'prompts/list':
        return {
          prompts: {
            prime_system: { content: 'You are Prime.', is_default: true, last_updated: '2025-01-01' },
            root_agent_system: { content: 'You are a root agent.', is_default: true, last_updated: '2025-01-01' },
            sub_agent_system: { content: 'You are a sub agent.', is_default: true, last_updated: '2025-01-01' },
            tangle_maker: { content: 'You make tangles.', is_default: true, last_updated: '2025-01-01' },
            tangle_reviewer: { content: 'Review tangles for tree structure, leaf code refs, and minimal actionable fixes.', is_default: true, last_updated: '2025-01-01' },
          },
        }

      case 'prompts/get':
        return { prompt: { content: 'You are Prime.', is_default: true, last_updated: '2025-01-01' } }

      case 'prompts/update':
        return { prompt: { content: msg.params.content ?? '', is_default: false, last_updated: new Date().toISOString() } }

      case 'prompts/reset':
        return { prompt: { content: 'You are Prime.', is_default: true, last_updated: new Date().toISOString() } }

      case 'run/start':
        return { status: 'running', run_id: 1, spec_ref: msg.params.tangle_ref, command: msg.params.command }

      case 'run/stop':
        return { status: 'idle' }

      case 'run/status':
        return { status: 'idle' }

      case 'ui/openTab':
      case 'ui/closeTab':
      case 'ui/setActiveTab':
      case 'ui/updateLayout':
      case 'ui/setTheme':
      case 'ui/saveTab':
        return {}

      default:
        console.warn('[MockBackend] unhandled method:', msg.method)
        return { error: { code: -32601, message: `Method not found: ${msg.method}` } }
    }
  }
}
