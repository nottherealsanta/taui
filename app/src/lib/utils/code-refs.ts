import { backendClient } from '$services/backend-client'

export type CodeRefKind = 'symbol' | 'lines'

export interface ParsedCodeRef {
  raw: string
  filePath: string
  target: string
  refKind: CodeRefKind
}

export interface ResolvedCodeRef extends ParsedCodeRef {
  content: string | null
  language: string | null
  resolvedStart: number | null
  resolvedEnd: number | null
  diagnostic: string
  error?: string
}

const TEXT_CODE_REF_RE = /(^|[\s([{'"`>])([A-Za-z0-9_./-]+\.[A-Za-z0-9]+):([A-Za-z0-9_.-]+)/g
const STANDALONE_CODE_REF_RE = /^(?:->|→)?\s*([A-Za-z0-9_./-]+\.[A-Za-z0-9]+):([A-Za-z0-9_.-]+)\s*$/
const LINE_RANGE_RE = /^\d+(?:-\d+)?$/

const resolveCache = new Map<string, Promise<ResolvedCodeRef>>()

export function codeRefKey(ref: Pick<ParsedCodeRef, 'filePath' | 'target' | 'refKind'>): string {
  return `${ref.filePath}:${ref.target}:${ref.refKind}`
}

export function inferCodeRefKind(target: string): CodeRefKind {
  return LINE_RANGE_RE.test(target) ? 'lines' : 'symbol'
}

export function parseStandaloneCodeRef(text: string): ParsedCodeRef | null {
  const trimmed = text.trim()
  const match = STANDALONE_CODE_REF_RE.exec(trimmed)
  if (!match) return null

  const filePath = match[1]
  const target = match[2]
  return {
    raw: `${filePath}:${target}`,
    filePath,
    target,
    refKind: inferCodeRefKind(target),
  }
}

export function findCodeRefsInText(text: string): Array<{ start: number; end: number; ref: ParsedCodeRef }> {
  const matches: Array<{ start: number; end: number; ref: ParsedCodeRef }> = []
  const regex = new RegExp(TEXT_CODE_REF_RE)
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    const prefix = match[1] ?? ''
    const filePath = match[2]
    const target = match[3]
    const raw = `${filePath}:${target}`
    const start = match.index + prefix.length
    const end = start + raw.length
    matches.push({
      start,
      end,
      ref: {
        raw,
        filePath,
        target,
        refKind: inferCodeRefKind(target),
      },
    })
  }

  return matches
}

export function formatCodeRefLabel(ref: Pick<ParsedCodeRef, 'filePath' | 'target'>): string {
  return `${ref.filePath}:${ref.target}`
}

export function previewCode(content: string | null | undefined, maxLines = 10): {
  text: string
  truncated: boolean
  lineCount: number
} {
  const lines = (content ?? '').split('\n')
  const truncated = lines.length > maxLines
  return {
    text: lines.slice(0, maxLines).join('\n'),
    truncated,
    lineCount: lines.length,
  }
}

export function inferLanguage(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    rs: 'rust',
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    py: 'python',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    md: 'markdown',
    html: 'html',
    css: 'css',
    toml: 'toml',
    sh: 'shell',
    svelte: 'html',
  }
  return map[ext] ?? 'plaintext'
}

export async function resolveCodeRef(ref: ParsedCodeRef): Promise<ResolvedCodeRef> {
  const key = codeRefKey(ref)
  const existing = resolveCache.get(key)
  if (existing) return existing

  const pending = backendClient
    .codeResolve(ref.filePath, ref.target, ref.refKind)
    .then((resolved) => ({
      ...ref,
      content: resolved.content,
      language: resolved.language,
      resolvedStart: resolved.resolvedStart,
      resolvedEnd: resolved.resolvedEnd,
      diagnostic: resolved.diagnostic,
      error: resolved.error,
    }))
    .catch((error) => {
      resolveCache.delete(key)
      throw error
    })

  resolveCache.set(key, pending)
  return pending
}

export function readCodeRefFromDataset(el: HTMLElement): ParsedCodeRef | null {
  const filePath = el.dataset.codeRefPath
  const target = el.dataset.codeRefTarget
  const refKind = el.dataset.codeRefKind
  if (!filePath || !target || (refKind !== 'symbol' && refKind !== 'lines')) {
    return null
  }

  return {
    raw: `${filePath}:${target}`,
    filePath,
    target,
    refKind,
  }
}
