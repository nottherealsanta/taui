// ─── Primitives ───────────────────────────────────────────────────────────────
// NodeId is a Vec index in the Rust implementation; we keep it as number.
export type NodeId = number
export type SpecRef = string

// ─── Agent types ─────────────────────────────────────────────────────────────

export type AgentState =
  | 'idle'
  | 'running'
  | 'thinking'
  | 'tool_execution'
  | 'asking_question'
  | 'waiting_for_answer'
  | 'stopping'
  | 'done'
  | { unknown: string }

export function agentStateIsActive(s: AgentState): boolean {
  return (
    s === 'running' ||
    s === 'thinking' ||
    s === 'tool_execution' ||
    s === 'asking_question' ||
    s === 'waiting_for_answer'
  )
}

export function agentStateFromString(s: string): AgentState {
  switch (s) {
    case 'idle': return 'idle'
    case 'running': return 'running'
    case 'thinking': return 'thinking'
    case 'tool_execution': return 'tool_execution'
    case 'asking_question': return 'asking_question'
    case 'waiting_for_answer': return 'waiting_for_answer'
    case 'stopping': return 'stopping'
    case 'done': return 'done'
    default: return { unknown: s }
  }
}

export type AgentTier = 'high' | 'medium' | 'low'

export type AgentType = 'root' | 'sub_agent'

export const PRIME_AGENT_ID = '__prime__'

/** Color hex values for root agent display names. */
export const AGENT_COLOR_HEX: Record<string, string> = {
  blue: '#3ab6e4',
  cyan: '#3ab6e4',
  green: '#72e93a',
  lime: '#72e93a',
  yellow: '#f5d700',
  amber: '#f5d700',
  magenta: '#da63de',
  pink: '#da63de',
  violet: '#da63de',
  orange: '#ff5a00',
}

export interface PrimeMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface PrimeHistoryMessage {
  role: 'user' | 'assistant' | 'tool' | 'divider'
  content: string
  seq?: number | null
  tool_call_id?: string
  name?: string
  metadata?: Record<string, unknown>
}

export interface PrimeHistoryPage {
  messages: PrimeHistoryMessage[]
  has_more: boolean
  oldest_seq: number | null
}

/** An in-flight or completed tool call inside Prime's streaming loop. */
export interface PrimeToolCall {
  callId: string
  toolName: string
  arguments: unknown
  result?: string | null
  error?: string | null
  durationMs?: number | null
  status: 'running' | 'done' | 'error'
}

/** A sub-agent launched from Prime's context. */
export interface PrimeSubAgentEntry {
  subAgentId: string
  task: string
  status: 'running' | 'done' | 'error'
  result?: string | null
  events: AgentDetailEvent[]
}

/** An entry in the Prime chat stream — text, tool, sub-agent, or agent-launch. */
export type PrimeChatEntry =
  | { kind: 'user'; content: string; seq?: number | null }
  | { kind: 'assistant'; content: string; seq?: number | null }
  | { kind: 'assistant-streaming'; content: string; seq?: number | null }
  | { kind: 'context-divider'; label: string; seq?: number | null }
  | { kind: 'tool'; tool: PrimeToolCall; seq?: number | null }
  | { kind: 'sub_agent'; subAgent: PrimeSubAgentEntry; seq?: number | null }
  | { kind: 'agent-launched'; agentId: string; displayName: string; task: string; seq?: number | null }

export interface PrimeReplyTarget {
  role: 'user' | 'assistant'
  content: string
  index: number
}

export interface AgentInfo {
  agentId: string
  specRef: SpecRef
  state: AgentState
  tier: AgentTier
  /** Most recent ephemeral tool brief (shown above the message bar). */
  toolBrief: string | null
  agentType: AgentType
  displayName: string
}

export interface PendingQuestion {
  agentId: string
  questionNodeRef: SpecRef
  question: string
  options: string[]
}

export type AgentDetailEvent =
  | { type: 'message'; role: string; content: string }
  | { type: 'toolCall'; callId: string; toolName: string; arguments: unknown }
  | {
      type: 'toolResult'
      callId: string
      output: string | null
      error: string | null
      durationMs: number | null
    }
  | { type: 'token'; text: string }
  | { type: 'stateChange'; state: AgentState }

// ─── Editor modes ────────────────────────────────────────────────────────────

export type EditorMode = 'normal' | 'selection' | 'editing'

export type MetadataEditTarget =
  | { kind: 'codeRef'; nodeId: NodeId; refIndex: number }
  | { kind: 'verification'; nodeId: NodeId }
  | { kind: 'dependsOn'; nodeId: NodeId; index: number }
  | { kind: 'relatedTo'; nodeId: NodeId; index: number }

// ─── Spec node ───────────────────────────────────────────────────────────────

export interface SpecNode {
  id: NodeId
  specRef: SpecRef
  markdown: string
  parent: NodeId | null
  children: NodeId[]
  collapsed: boolean
  status: string | null
  codeRefs: string[]
  verification: string | null
  dependsOn: string[]
  relatedTo: string[]
}

/** Flattened, renderable row derived from the tree for the virtual list. */
export interface FlatNode {
  /** 'node' for real spec nodes; 'codeRef' for code_ref sub-rows. */
  kind: 'node' | 'codeRef'
  id: NodeId
  depth: number
  markdown: string
  selected: boolean
  selectionHighlighted: boolean
  collapsed: boolean
  hasChildren: boolean
  codeRefs: string[]
  verification: string | null
  dependsOn: string[]
  relatedTo: string[]
  /** Agent ID currently active on this node. */
  agentId: string | null
  locked: boolean
  hasQuestion: boolean
  /** Only set when kind === 'codeRef': the raw ref string (e.g. `src/app.rs:10-20`). */
  codeRefValue?: string
  /** Only set when kind === 'codeRef': index in the parent node's codeRefs array. */
  codeRefIndex?: number
  /** Only set when kind === 'codeRef': the NodeId of the owning spec node. */
  parentNodeId?: NodeId
}

// ─── Backend wire types ───────────────────────────────────────────────────────

/** Raw node from `spec/getTreeDetailed`. */
export interface BackendNode {
  id: string
  spec_ref?: string
  tangle_ref?: string
  depth: number
  markdown: string
  status?: string | null
  collapsed?: boolean
  code_refs?: string[]
  verification?: string | null
  depends_on?: string[]
  related_to?: string[]
}

export interface BackendTreeResponse {
  nodes: BackendNode[]
}

export interface BackendInitializeResponse {
  protocolVersion: string
  serverName: string
  workspace: string | null
  projectTitle?: string
  capabilities: unknown
  model?: string
}

export interface BackendUpdateNodeResponse {
  previous_spec_ref: string
  previous_tangle_ref?: string
  node: BackendNode
  tree_changed: boolean
}

export interface CodeRefPreview {
  rawRef: string
  filePath: string
  lineStart: number | null
  lineEnd: number | null
  previewStart: number | null
  previewEnd: number | null
  content: string
  truncated: boolean
  error: string | null
}

export interface CodeRefsResponse {
  refs: CodeRefPreview[]
}

// ─── Run / Terminal types ─────────────────────────────────────────────────────

export type RunStatus = 'idle' | 'running' | 'completed' | 'stopped' | 'error'

export interface RunLine {
  stream: 'stdout' | 'stderr'
  text: string
}

export interface RunState {
  status: RunStatus
  runId: number | null
  specRef: SpecRef | null
  command: string | null
  exitCode: number | null
  /** Streamed output lines */
  lines: RunLine[]
}

export interface BackendRunState {
  status: string
  run_id?: number | null
  spec_ref?: string | null
  tangle_ref?: string | null
  command?: string | null
  exit_code?: number | null
}

export interface SourceRangeResponse {
  file_path: string
  line_start: number | null
  line_end: number | null
  preview_start: number | null
  preview_end: number | null
  content: string
  truncated: boolean
  error?: string | null
}

// ─── File system types ────────────────────────────────────────────────────────

export interface FileEntry {
  name: string
  path: string       // relative to workspace root
  isDir: boolean
  extension: string
}

export interface OpenTab {
  id: string          // unique tab ID
  filePath: string
  title: string
  isDirty: boolean
  content: string
  frontmatter?: Record<string, unknown>
}

export interface SearchResult {
  filePath: string
  lineNumber: number
  lineContent: string
  matchStart: number
  matchEnd: number
}

// ─── Backend state ────────────────────────────────────────────────────────────

export type BackendConnectionState =
  | 'offline'
  | 'connecting'
  | 'ready'
  | { error: string }
