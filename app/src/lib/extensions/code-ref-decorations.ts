import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import {
  codeRefKey,
  findCodeRefsInText,
  formatCodeRefLabel,
  parseStandaloneCodeRef,
  previewCode,
  resolveCodeRef,
  type ParsedCodeRef,
} from '$lib/utils/code-refs'

const CODE_REF_DECORATIONS_KEY = new PluginKey('codeRefDecorations')

function applyCodeRefDataset(el: HTMLElement, ref: ParsedCodeRef): void {
  el.dataset.codeRefPath = ref.filePath
  el.dataset.codeRefTarget = ref.target
  el.dataset.codeRefKind = ref.refKind
}

function renderPreviewState(root: HTMLElement, title: string, body: string, footer = ''): void {
  root.innerHTML = `
    <div class="code-ref-inline-preview__header">
      <span class="code-ref-inline-preview__badge">code</span>
      <span class="code-ref-inline-preview__title">${escapeHtml(title)}</span>
    </div>
    <pre class="code-ref-inline-preview__body">${body}</pre>
    ${footer ? `<div class="code-ref-inline-preview__footer">${escapeHtml(footer)}</div>` : ''}
  `
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function createStandalonePreviewWidget(ref: ParsedCodeRef): HTMLElement {
  const root = document.createElement('div')
  root.className = 'code-ref-inline-preview'
  root.setAttribute('role', 'button')
  root.setAttribute('tabindex', '0')
  root.contentEditable = 'false'
  applyCodeRefDataset(root, ref)

  const emitOpen = () => {
    window.dispatchEvent(new CustomEvent('taui:open-code-ref', { detail: ref }))
  }

  root.addEventListener('click', (event) => {
    event.preventDefault()
    event.stopPropagation()
    emitOpen()
  })

  root.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      event.stopPropagation()
      emitOpen()
    }
  })

  const title = formatCodeRefLabel(ref)
  renderPreviewState(root, title, 'Loading preview…')

  void resolveCodeRef(ref)
    .then((resolved) => {
      const preview = previewCode(resolved.content, 10)
      const lineLabel = resolved.resolvedStart !== null
        ? `Lines ${resolved.resolvedStart}${resolved.resolvedEnd && resolved.resolvedEnd !== resolved.resolvedStart ? `–${resolved.resolvedEnd}` : ''}`
        : 'Resolved preview'
      const footer = preview.truncated ? `${lineLabel} • showing first 10 lines` : lineLabel
      renderPreviewState(root, title, escapeHtml(preview.text || 'No preview available.'), footer)
    })
    .catch((error) => {
      renderPreviewState(root, title, escapeHtml(`Unable to load preview.\n${String(error)}`))
    })

  return root
}

function buildDecorations(doc: any): DecorationSet {
  const decorations: Decoration[] = []

  doc.descendants((node: any, pos: number, parent: any) => {
    if (node.type?.name === 'paragraph') {
      const standalone = parseStandaloneCodeRef(node.textContent ?? '')
      if (standalone) {
        decorations.push(
          Decoration.node(pos, pos + node.nodeSize, {
            class: 'code-ref-standalone-paragraph',
          }),
        )
        decorations.push(
          Decoration.widget(
            pos + node.nodeSize,
            () => createStandalonePreviewWidget(standalone),
            {
              side: -1,
              key: `code-ref-preview-${pos}-${codeRefKey(standalone)}`,
            },
          ),
        )
      }
    }

    if (!node.isText) return true
    if (parent?.type?.name === 'codeBlock') return true

    const text = node.text ?? ''
    for (const match of findCodeRefsInText(text)) {
      decorations.push(
        Decoration.inline(pos + match.start, pos + match.end, {
          class: 'code-ref-chip',
          'data-code-ref-path': match.ref.filePath,
          'data-code-ref-target': match.ref.target,
          'data-code-ref-kind': match.ref.refKind,
          title: formatCodeRefLabel(match.ref),
        }),
      )
    }

    return true
  })

  return DecorationSet.create(doc, decorations)
}

export const CodeRefDecorations = Extension.create({
  name: 'codeRefDecorations',

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: CODE_REF_DECORATIONS_KEY,
        state: {
          init(_, { doc }) {
            return buildDecorations(doc)
          },
          apply(tr, decorationSet, _oldState, newState) {
            if (!tr.docChanged) return decorationSet
            return buildDecorations(newState.doc)
          },
        },
        props: {
          decorations(state) {
            return CODE_REF_DECORATIONS_KEY.getState(state) as DecorationSet
          },
          handleDOMEvents: {
            mousedown(_view, event) {
              const target = event.target as HTMLElement | null
              if (target?.closest('.code-ref-chip, .code-ref-inline-preview')) {
                event.preventDefault()
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
