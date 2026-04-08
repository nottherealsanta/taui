/**
 * Typography constants — ported from ui/src/app/typography.rs.
 * Used by components for inline styles where Tailwind utilities can't reach
 * (e.g. depth-based dynamic font sizes in the tree view).
 */

/** IBM Plex Sans — body text everywhere. */
export const BODY_FONT_FAMILY = '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif'

/** JetBrains Mono — code blocks, inline code, markdown content editor. */
export const CODE_FONT_FAMILY = '"JetBrains Mono", ui-monospace, "Cascadia Code", monospace'

/** Pixels of indentation added per depth level in the spec tree. */
export const INDENT_PER_LEVEL = 24 // px(24.0) in Rust

/** Max width of the content area inside a spec node. */
export const MAX_CONTENT_WIDTH = 820 // px(820.0) in Rust

/** Default text size for markdown body content. */
export const MARKDOWN_TEXT_SIZE = 16 // px(16.0)

/** Line height for markdown body content. */
export const MARKDOWN_LINE_HEIGHT = 1.45

/** Body text size used throughout the shell UI. */
export const BODY_TEXT_SIZE = 13 // px

// ─── Depth → heading style ────────────────────────────────────────────────────
// Ported from depth_to_heading_style() in typography.rs.

export interface HeadingStyle {
  fontSize: number  // px
  fontWeight: 400 | 500 | 600 | 700
}

export function depthToHeadingStyle(depth: number): HeadingStyle {
  switch (depth) {
    case 0:
      return { fontSize: 16, fontWeight: 400 }
    case 1:
      return { fontSize: 22, fontWeight: 600 }
    case 2:
      return { fontSize: 18, fontWeight: 500 }
    default:
      return { fontSize: MARKDOWN_TEXT_SIZE, fontWeight: 400 }
  }
}

/**
 * CSS style object for a tree row at the given depth.
 * Used by TreeRow.svelte to apply depth-appropriate heading styles inline.
 */
export function depthToRowStyle(depth: number): { fontSize: string; fontWeight: number } {
  const { fontSize, fontWeight } = depthToHeadingStyle(depth)
  return {
    fontSize: `${fontSize}px`,
    fontWeight,
  }
}

/**
 * Indent offset in pixels for a given depth level.
 * Depth 0 (tree roots) get no indent; each level adds INDENT_PER_LEVEL.
 */
export function indentPx(depth: number): number {
  return depth * INDENT_PER_LEVEL
}

/**
 * Split root node markdown into (title, body).
 * Title = first non-empty line with leading `#` stripped.
 * Body = remaining lines.
 * Ported from split_root_markdown() in typography.rs.
 */
export function splitRootMarkdown(markdown: string): [title: string, body: string] {
  const lines = markdown.split('\n')
  let title = ''
  let bodyStart = 0

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (trimmed !== '') {
      title = trimmed.replace(/^#+\s*/, '')
      bodyStart = i + 1
      break
    }
  }

  const body = lines.slice(bodyStart).join('\n').trim()
  return [title, body]
}
