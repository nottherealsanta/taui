export function specRefToFilePath(specRef: string): string {
  return specRef.split('#')[0] ?? specRef
}

/**
 * Strip YAML frontmatter (--- delimited block at start) from markdown content.
 * Returns the body content after the closing ---.
 */
export function stripFrontmatter(content: string): string {
  if (!content.startsWith('---\n') && !content.startsWith('---\r\n')) return content
  const end = content.indexOf('\n---\n', 4)
  if (end === -1) {
    const endR = content.indexOf('\r\n---\r\n', 4)
    if (endR === -1) return content
    return content.slice(endR + 7).replace(/^\n+/, '')
  }
  return content.slice(end + 5).replace(/^\n+/, '')
}

export function basenameWithoutMarkdown(filePath: string): string {
  const name = filePath.split('/').pop() ?? filePath
  return name.replace(/\.md$/i, '')
}

export function formatPathSegment(segment: string): string {
  return segment
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

export function markdownLineLabel(markdown: string): string {
  const firstNonEmpty = markdown
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0)

  if (!firstNonEmpty) return 'Untitled'

  return firstNonEmpty
    .replace(/^[-*+]\s+/, '')
    .replace(/^#+\s*/, '')
    .trim() || 'Untitled'
}

export function deriveSpecTitle(
  filePath: string,
  content: string,
  frontmatter?: Record<string, unknown>,
): string {
  const fmTitle = frontmatter?.title
  if (typeof fmTitle === 'string' && fmTitle.trim()) {
    return fmTitle.trim()
  }

  const firstHeading = content.match(/^#\s+(.+)$/m)?.[1]?.trim()
  if (firstHeading) {
    return firstHeading
  }

  return formatPathSegment(basenameWithoutMarkdown(filePath))
}

export function commonLeadingSegments(paths: string[]): string[] {
  if (paths.length === 0) return []

  const splitPaths = paths.map((path) => path.split('/').filter(Boolean))
  const first = splitPaths[0]
  const shared: string[] = []

  for (let index = 0; index < first.length; index += 1) {
    const segment = first[index]
    if (splitPaths.every((parts) => parts[index] === segment)) {
      shared.push(segment)
      continue
    }
    break
  }

  return shared
}