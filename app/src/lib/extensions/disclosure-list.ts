/**
 * DisclosureList — TipTap extension for progressive disclosure in spec documents.
 *
 * Two levels of disclosure:
 *
 * 1. **Heading sections** — H2, H3, etc. headings get chevrons. Collapsing a
 *    heading hides all sibling content until the next heading of the same or
 *    higher level. H1 (the document title) is never collapsible.
 *
 * 2. **Nested list items** — Bullet/ordered list items that contain a nested
 *    list get chevrons. Collapsing hides the nested list.
 *
 * **Default behavior: all collapsed.** When a document loads, every
 * collapsible node starts collapsed so users see only the top-level
 * structure (H1 title + H2 headings). They drill down one level at a time
 * by clicking chevrons. Expanding an H2 reveals its content (paragraphs,
 * lists, H3s, etc.) — nested H3s are still collapsed, list items with
 * children are still collapsed. The user controls depth.
 *
 * Markdown roundtrip is preserved — collapse state is editor-only and
 * doesn't affect serialization.
 */

import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

const DISCLOSURE_KEY = new PluginKey('disclosureList')

/** Set of collapsed node positions (stored by identity, re-mapped on doc changes). */
type CollapsedSet = Set<number>

// ─── Heading helpers ───────────────────────────────────────────────────────────

/**
 * Extract the heading level (1-6) from a node, or 0 if not a heading.
 */
function headingLevel(node: any): number {
  if (node.type.name === 'heading') {
    return node.attrs?.level ?? 0
  }
  return 0
}

/**
 * Represents a heading section: the heading node and the range of sibling
 * content it "owns" (everything until the next same-or-higher-level heading).
 */
interface HeadingSection {
  pos: number       // position of the heading node in the doc
  level: number     // heading level (2, 3, 4, ...)
  nodeSize: number  // size of the heading node itself
  /** Sibling nodes that belong to this section (between heading and next boundary) */
  contentRange: { from: number; to: number } | null
}

/**
 * Walk the doc's top-level children and identify heading sections.
 * Returns sections for H2+ headings that have content after them.
 */
function findHeadingSections(doc: any): HeadingSection[] {
  const sections: HeadingSection[] = []
  const topChildren: { node: any; pos: number }[] = []

  // Collect top-level children with their positions
  doc.forEach((node: any, offset: number) => {
    topChildren.push({ node, pos: offset })
  })

  for (let i = 0; i < topChildren.length; i++) {
    const { node, pos } = topChildren[i]
    const level = headingLevel(node)

    // Skip non-headings and H1 (document title)
    if (level < 2) continue

    // Find where this section's content ends: at the next heading of
    // same or higher (lower number) level, or at the end of the doc.
    let contentEnd = doc.content.size
    for (let j = i + 1; j < topChildren.length; j++) {
      const nextLevel = headingLevel(topChildren[j].node)
      if (nextLevel > 0 && nextLevel <= level) {
        contentEnd = topChildren[j].pos
        break
      }
    }

    const contentStart = pos + node.nodeSize
    const hasContent = contentStart < contentEnd

    sections.push({
      pos,
      level,
      nodeSize: node.nodeSize,
      contentRange: hasContent ? { from: contentStart, to: contentEnd } : null,
    })
  }

  return sections
}

// ─── List helpers ──────────────────────────────────────────────────────────────

/**
 * Check if a listItem node contains a nested bulletList (i.e. has children).
 */
function listItemHasNestedList(node: any): boolean {
  let found = false
  node.forEach((child: any) => {
    if (child.type.name === 'bulletList' || child.type.name === 'orderedList') {
      found = true
    }
  })
  return found
}

/**
 * Find the position of the nested list within a listItem.
 */
function findNestedListPos(node: any, offset: number): { from: number; to: number } | null {
  let result: { from: number; to: number } | null = null
  let pos = offset + 1 // skip into the listItem
  node.forEach((child: any) => {
    if (child.type.name === 'bulletList' || child.type.name === 'orderedList') {
      result = { from: pos, to: pos + child.nodeSize }
    }
    pos += child.nodeSize
  })
  return result
}

// ─── Shared helpers ────────────────────────────────────────────────────────────

/**
 * Collect all positions of collapsible nodes (headings + list items).
 * Used to default-collapse everything on document load.
 */
function collectAllCollapsiblePositions(doc: any): CollapsedSet {
  const positions: CollapsedSet = new Set()

  // Heading sections (H2+)
  for (const section of findHeadingSections(doc)) {
    if (section.contentRange) {
      positions.add(section.pos)
    }
  }

  // Nested list items
  doc.descendants((node: any, pos: number) => {
    if (node.type.name === 'listItem' && listItemHasNestedList(node)) {
      positions.add(pos)
    }
    return true
  })

  return positions
}

/**
 * Create the SVG chevron button element used for both headings and list items.
 */
function createChevronButton(
  pos: number,
  isCollapsed: boolean,
  view: EditorView | null,
  extraClass?: string,
): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.className = `disclosure-chevron${isCollapsed ? ' collapsed' : ''}${extraClass ? ` ${extraClass}` : ''}`
  btn.setAttribute('aria-label', isCollapsed ? 'expand' : 'collapse')
  btn.setAttribute('data-disclosure-pos', String(pos))
  btn.contentEditable = 'false'

  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M6 3.5L11 8L6 12.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`

  btn.addEventListener('mousedown', (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (!view) return
    const tr = view.state.tr.setMeta(DISCLOSURE_KEY, { pos })
    view.dispatch(tr)
  })

  return btn
}

// ─── Build decorations ─────────────────────────────────────────────────────────

/**
 * Build decorations for both heading sections and nested list items.
 */
function buildDecorations(doc: any, collapsed: CollapsedSet, view: EditorView | null): DecorationSet {
  const decorations: Decoration[] = []

  // ── Heading sections ──

  // Track which ranges are hidden by collapsed headings, so we can
  // skip adding decorations for content that's already hidden by a
  // parent heading collapse.
  const hiddenRanges: { from: number; to: number }[] = []

  for (const section of findHeadingSections(doc)) {
    if (!section.contentRange) continue

    // Check if this heading itself is inside a hidden range
    const headingHidden = hiddenRanges.some(
      (r) => section.pos >= r.from && section.pos < r.to
    )
    if (headingHidden) continue

    const isCollapsed = collapsed.has(section.pos)

    // Widget: chevron inside the heading
    const chevronWidget = Decoration.widget(
      section.pos + 1, // inside the heading node
      () => createChevronButton(section.pos, isCollapsed, view, 'disclosure-heading-chevron'),
      { side: -1, key: `heading-chevron-${section.pos}-${isCollapsed}` },
    )
    decorations.push(chevronWidget)

    // Node decoration on the heading itself
    decorations.push(
      Decoration.node(section.pos, section.pos + section.nodeSize, {
        class: `disclosure-heading${isCollapsed ? ' collapsed' : ''}`,
      })
    )

    // If collapsed, hide each top-level sibling node in the content range
    if (isCollapsed && section.contentRange) {
      hiddenRanges.push(section.contentRange)

      // We need to hide individual top-level nodes in the range
      // by iterating the doc's children
      let pos = 0
      doc.forEach((child: any, offset: number) => {
        if (offset >= section.contentRange!.from && offset < section.contentRange!.to) {
          decorations.push(
            Decoration.node(offset, offset + child.nodeSize, {
              class: 'disclosure-hidden',
            })
          )
        }
      })
    }
  }

  // ── Nested list items ──

  doc.descendants((node: any, pos: number) => {
    if (node.type.name !== 'listItem') return true

    const hasChildren = listItemHasNestedList(node)
    if (!hasChildren) return true

    const isCollapsed = collapsed.has(pos)

    const chevronWidget = Decoration.widget(pos + 1, () => {
      return createChevronButton(pos, isCollapsed, view)
    }, { side: -1, key: `chevron-${pos}-${isCollapsed}` })

    decorations.push(chevronWidget)

    // Node decoration on the listItem: add class
    decorations.push(
      Decoration.node(pos, pos + node.nodeSize, {
        class: `disclosure-item has-children${isCollapsed ? ' collapsed' : ''}`,
      })
    )

    // If collapsed, hide the nested list(s) via node decoration
    if (isCollapsed) {
      const nestedPos = findNestedListPos(node, pos)
      if (nestedPos) {
        decorations.push(
          Decoration.node(nestedPos.from, nestedPos.to, {
            class: 'disclosure-hidden',
          })
        )
      }
    }

    return true
  })

  return DecorationSet.create(doc, decorations)
}

// ─── Position remapping ────────────────────────────────────────────────────────

/**
 * Remap collapsed positions after a document change.
 */
function remapCollapsed(collapsed: CollapsedSet, mapping: any): CollapsedSet {
  const next: CollapsedSet = new Set()
  for (const pos of collapsed) {
    const mapped = mapping.map(pos, 1)
    if (mapped != null) {
      next.add(mapped)
    }
  }
  return next
}

// ─── Extension ─────────────────────────────────────────────────────────────────

export const DisclosureList = Extension.create({
  name: 'disclosureList',

  addProseMirrorPlugins() {
    let editorView: EditorView | null = null

    return [
      new Plugin({
        key: DISCLOSURE_KEY,

        view(view) {
          editorView = view
          return {
            update(view) {
              editorView = view
            },
            destroy() {
              editorView = null
            },
          }
        },

        state: {
          init(_, { doc }) {
            // Default all collapsible items to collapsed so the user sees
            // only the top-level structure on document open.
            const collapsed = collectAllCollapsiblePositions(doc)
            return {
              collapsed,
              decorations: buildDecorations(doc, collapsed, null),
            }
          },
          apply(tr, value, oldState, newState) {
            const toggle = tr.getMeta(DISCLOSURE_KEY) as { pos: number } | undefined

            let { collapsed } = value

            if (tr.docChanged) {
              // Detect full document replacement (e.g. setContent when switching tabs).
              const isFullReplace =
                tr.steps.length > 0 &&
                tr.mapping.maps.some((map: any) => {
                  let coversAll = false
                  map.forEach((_: number, __: number, from: number, to: number) => {
                    if (from === 0 && to >= oldState.doc.content.size) {
                      coversAll = true
                    }
                  })
                  return coversAll
                })

              if (isFullReplace) {
                collapsed = collectAllCollapsiblePositions(newState.doc)
              } else {
                collapsed = remapCollapsed(collapsed, tr.mapping)
              }
            }

            if (toggle) {
              collapsed = new Set(collapsed)
              if (collapsed.has(toggle.pos)) {
                collapsed.delete(toggle.pos)
              } else {
                collapsed.add(toggle.pos)
              }
            }

            if (toggle || tr.docChanged) {
              return {
                collapsed,
                decorations: buildDecorations(newState.doc, collapsed, editorView),
              }
            }

            return value
          },
        },

        props: {
          decorations(state) {
            const pluginState = DISCLOSURE_KEY.getState(state) as
              | { decorations: DecorationSet }
              | undefined
            return pluginState?.decorations ?? DecorationSet.empty
          },

          handleDOMEvents: {
            mousedown(_view: EditorView, event: MouseEvent) {
              const target = event.target as HTMLElement
              if (target.closest('.disclosure-chevron')) {
                return true
              }
              return false
            },
          },
        },
      }),
    ]
  },
})
