<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { EditorSelection, EditorState, RangeSetBuilder } from '@codemirror/state'
  import { Decoration, EditorView, ViewPlugin, keymap } from '@codemirror/view'
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdown } from '@codemirror/lang-markdown'
  import { tabStore } from '$stores/tabs.svelte'

  interface Props {
    content: string
    filePath: string
    tabId: string
    readOnly?: boolean
  }

  const { content, filePath, tabId, readOnly = false }: Props = $props()

  let containerEl: HTMLDivElement | undefined = $state()
  let editorView: EditorView | null = null
  let applyingExternalContent = false
  const hiddenTokenDecoration = Decoration.mark({ class: 'cm-live-hidden-token' })

  const headingPattern = /^(\s{0,3})(#{1,6})(\s+)/
  const strongPatterns = [/\*\*([^*\n]+)\*\*/g, /__([^_\n]+)__/g]
  const emphasisPatterns = [/(^|[^*])\*([^*\n]+)\*(?!\*)/g, /(^|[^_])_([^_\n]+)_(?!_)/g]
  const inlineCodePattern = /`([^`\n]+)`/g

  interface LineBlock {
    startLine: number
    endLine: number
  }

  function findFrontmatterBlock(view: EditorView): LineBlock | null {
    if (view.state.doc.lines < 3) return null
    if (view.state.doc.line(1).text.trim() !== '---') return null

    for (let lineNumber = 2; lineNumber <= view.state.doc.lines; lineNumber += 1) {
      const text = view.state.doc.line(lineNumber).text.trim()
      if (text === '---' || text === '...') {
        return { startLine: 1, endLine: lineNumber }
      }
    }

    return null
  }

  function findCodeFenceBlocks(view: EditorView): LineBlock[] {
    const blocks: LineBlock[] = []
    let openFence: { lineNumber: number; marker: string; length: number } | null = null

    for (let lineNumber = 1; lineNumber <= view.state.doc.lines; lineNumber += 1) {
      const lineText = view.state.doc.line(lineNumber).text.trim()
      const match = /^(?<marker>`{3,}|~{3,})/.exec(lineText)
      if (!match?.groups?.['marker']) continue

      const marker = match.groups['marker']
      if (openFence === null) {
        openFence = { lineNumber, marker: marker[0], length: marker.length }
        continue
      }

      if (marker[0] === openFence.marker && marker.length >= openFence.length) {
        blocks.push({ startLine: openFence.lineNumber, endLine: lineNumber })
        openFence = null
      }
    }

    return blocks
  }

  function blockForLine(lineNumber: number, blocks: LineBlock[]): LineBlock | null {
    return blocks.find((block) => lineNumber >= block.startLine && lineNumber <= block.endLine) ?? null
  }

  function cursorWithinBlock(view: EditorView, block: LineBlock): boolean {
    const cursor = view.state.selection.main.head
    const start = view.state.doc.line(block.startLine).from
    const end = view.state.doc.line(block.endLine).to
    return cursor >= start && cursor <= end
  }

  interface PendingMark {
    from: number
    to: number
    decoration: Decoration
  }

  function collectInlineMarks(
    lineText: string,
    lineFrom: number,
    cursor: number,
  ): PendingMark[] {
    const marks: PendingMark[] = []

    // Collect inline code spans first so we can exclude strong/emphasis inside them
    const codeRanges: { from: number; to: number }[] = []
    for (const match of lineText.matchAll(inlineCodePattern)) {
      const idx = match.index ?? 0
      codeRanges.push({ from: idx, to: idx + match[0].length })
    }

    function insideCodeSpan(offset: number): boolean {
      return codeRanges.some((r) => offset >= r.from && offset < r.to)
    }

    for (const pattern of strongPatterns) {
      for (const match of lineText.matchAll(pattern)) {
        if (insideCodeSpan(match.index ?? 0)) continue
        const full = match[0]
        const inner = match[1]
        const start = lineFrom + (match.index ?? 0)
        const openEnd = start + 2
        const contentStart = openEnd
        const contentEnd = contentStart + inner.length
        const closeStart = start + full.length - 2
        const closeEnd = closeStart + 2
        const reveal = cursor >= start && cursor <= closeEnd

        marks.push({ from: contentStart, to: contentEnd, decoration: Decoration.mark({ class: 'cm-live-strong' }) })

        if (!reveal) {
          marks.push({ from: start, to: openEnd, decoration: hiddenTokenDecoration })
          marks.push({ from: closeStart, to: closeEnd, decoration: hiddenTokenDecoration })
        }
      }
    }

    for (const pattern of emphasisPatterns) {
      for (const match of lineText.matchAll(pattern)) {
        const prefix = match[1] ?? ''
        const markerOffset = (match.index ?? 0) + prefix.length
        if (insideCodeSpan(markerOffset)) continue
        const inner = match[2] ?? ''
        const start = lineFrom + markerOffset
        const openEnd = start + 1
        const contentStart = openEnd
        const contentEnd = contentStart + inner.length
        const closeStart = contentEnd
        const closeEnd = closeStart + 1
        const reveal = cursor >= start && cursor <= closeEnd

        marks.push({ from: contentStart, to: contentEnd, decoration: Decoration.mark({ class: 'cm-live-emphasis' }) })

        if (!reveal) {
          marks.push({ from: start, to: openEnd, decoration: hiddenTokenDecoration })
          marks.push({ from: closeStart, to: closeEnd, decoration: hiddenTokenDecoration })
        }
      }
    }

    for (const match of lineText.matchAll(inlineCodePattern)) {
      const full = match[0]
      const inner = match[1]
      const start = lineFrom + (match.index ?? 0)
      const openEnd = start + 1
      const contentStart = openEnd
      const contentEnd = contentStart + inner.length
      const closeStart = start + full.length - 1
      const closeEnd = closeStart + 1
      const reveal = cursor >= start && cursor <= closeEnd

      marks.push({ from: contentStart, to: contentEnd, decoration: Decoration.mark({ class: 'cm-live-inline-code' }) })

      if (!reveal) {
        marks.push({ from: start, to: openEnd, decoration: hiddenTokenDecoration })
        marks.push({ from: closeStart, to: closeEnd, decoration: hiddenTokenDecoration })
      }
    }

    marks.sort((a, b) => a.from - b.from || a.to - b.to)
    return marks
  }

  function buildLivePreviewDecorations(view: EditorView) {
    try {
      const builder = new RangeSetBuilder<Decoration>()
      const cursor = view.state.selection.main.head
      const lineCount = view.state.doc.lines
      const frontmatterBlock = findFrontmatterBlock(view)
      const codeFenceBlocks = findCodeFenceBlocks(view)

      for (let lineNumber = 1; lineNumber <= lineCount; lineNumber += 1) {
        const line = view.state.doc.line(lineNumber)
        const lineText = line.text
        const frontmatterLine = frontmatterBlock && lineNumber >= frontmatterBlock.startLine && lineNumber <= frontmatterBlock.endLine
        const codeFenceBlock = blockForLine(lineNumber, codeFenceBlocks)

        if (frontmatterLine && frontmatterBlock) {
          const reveal = cursorWithinBlock(view, frontmatterBlock)
          const isFenceLine = lineNumber === frontmatterBlock.startLine || lineNumber === frontmatterBlock.endLine

          builder.add(
            line.from,
            line.from,
            Decoration.line({ attributes: { class: 'cm-live-frontmatter-line' } }),
          )

          if (isFenceLine && !reveal) {
            builder.add(line.from, line.to, hiddenTokenDecoration)
          }
          continue
        }

        if (codeFenceBlock) {
          const reveal = cursorWithinBlock(view, codeFenceBlock)
          const isFenceLine = lineNumber === codeFenceBlock.startLine || lineNumber === codeFenceBlock.endLine

          builder.add(
            line.from,
            line.from,
            Decoration.line({ attributes: { class: 'cm-live-code-line' } }),
          )

          if (isFenceLine && !reveal) {
            builder.add(line.from, line.to, hiddenTokenDecoration)
          }
          continue
        }

        const headingMatch = headingPattern.exec(lineText)
        if (headingMatch) {
          const level = headingMatch[2].length
          const markerEnd = line.from + headingMatch[0].length
          const cursorOnLine = cursor >= line.from && cursor <= line.to

          builder.add(
            line.from,
            line.from,
            Decoration.line({ attributes: { class: `cm-live-heading-line cm-live-heading-${level}` } }),
          )

          if (!cursorOnLine) {
            builder.add(line.from, markerEnd, hiddenTokenDecoration)
          }
        }

        const inlineMarks = collectInlineMarks(lineText, line.from, cursor)
        for (const mark of inlineMarks) {
          builder.add(mark.from, mark.to, mark.decoration)
        }
      }

      return builder.finish()
    } catch (e) {
      console.warn('[LiveMarkdownEditor] decoration build failed:', e)
      return Decoration.none
    }
  }

  const livePreviewPlugin = ViewPlugin.fromClass(
    class {
      decorations

      constructor(view: EditorView) {
        this.decorations = buildLivePreviewDecorations(view)
      }

      update(update: { view: EditorView; docChanged: boolean; selectionSet: boolean; viewportChanged: boolean }) {
        if (update.docChanged || update.selectionSet || update.viewportChanged) {
          this.decorations = buildLivePreviewDecorations(update.view)
        }
      }
    },
    {
      decorations: (value) => value.decorations,
    },
  )

  const editorTheme = EditorView.theme({
    '&': {
      height: '100%',
      backgroundColor: 'var(--bg-surface)',
      color: 'var(--fg-primary)',
      fontFamily: 'var(--font-sans)',
      fontSize: '14px',
    },
    '.cm-scroller': {
      fontFamily: 'var(--font-sans)',
      lineHeight: '1.7',
      padding: '20px 24px 56px',
      overflow: 'auto',
    },
    '.cm-content': {
      maxWidth: 'var(--max-content-width)',
      minHeight: '100%',
      padding: '0',
      caretColor: 'var(--fg-accent)',
    },
    '.cm-focused': {
      outline: 'none',
    },
    '.cm-line': {
      padding: '0',
    },
    '.cm-selectionBackground, ::selection': {
      backgroundColor: 'var(--element-selected)',
    },
    '.cm-gutters': {
      display: 'none',
    },
    // Live preview token hiding — injected here so it bypasses Svelte CSS scoping
    '.cm-live-hidden-token': {
      fontSize: '0',
      lineHeight: '0',
      overflow: 'hidden',
      color: 'transparent',
    },
  })

  function saveCurrentTab(): boolean {
    void tabStore.save(tabId)
    return true
  }

  onMount(() => {
    if (!containerEl) return

    editorView = new EditorView({
      parent: containerEl,
      state: EditorState.create({
        doc: content,
        extensions: [
          history(),
          markdown(),
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          livePreviewPlugin,
          editorTheme,
          keymap.of([
            ...defaultKeymap,
            ...historyKeymap,
            { key: 'Mod-s', run: saveCurrentTab },
          ]),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged || applyingExternalContent) return
            tabStore.updateContent(tabId, update.state.doc.toString())
          }),
        ],
      }),
    })
  })

  $effect(() => {
    if (!editorView) return

    const currentContent = editorView.state.doc.toString()
    if (currentContent === content) return

    const nextCursor = Math.min(editorView.state.selection.main.head, content.length)
    applyingExternalContent = true
    editorView.dispatch({
      changes: { from: 0, to: currentContent.length, insert: content },
      selection: EditorSelection.cursor(nextCursor),
    })
    applyingExternalContent = false
  })

  onDestroy(() => {
    editorView?.destroy()
    editorView = null
  })
</script>

<div class="live-markdown-editor selectable">
  <div class="editor-header">
    <span class="file-path">{filePath}</span>
  </div>
  <div class="editor-shell" bind:this={containerEl}></div>
</div>

<style lang="postcss">
  .live-markdown-editor {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 34px;
    padding: 0 12px;
    border-bottom: 1px solid var(--border-variant);
    background-color: var(--bg-surface);
    color: var(--fg-muted);
    font-size: 11px;
    letter-spacing: 0.02em;
    flex-shrink: 0;
  }

  .file-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .editor-shell {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .live-markdown-editor :global(.cm-live-heading-line) {
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .live-markdown-editor :global(.cm-live-heading-1) {
    font-size: 2rem;
    line-height: 1.2;
  }

  .live-markdown-editor :global(.cm-live-heading-2) {
    font-size: 1.6rem;
    line-height: 1.25;
  }

  .live-markdown-editor :global(.cm-live-heading-3) {
    font-size: 1.35rem;
    line-height: 1.3;
  }

  .live-markdown-editor :global(.cm-live-heading-4),
  .live-markdown-editor :global(.cm-live-heading-5),
  .live-markdown-editor :global(.cm-live-heading-6) {
    font-size: 1.1rem;
    line-height: 1.35;
  }

  .live-markdown-editor :global(.cm-live-strong) {
    font-weight: 700;
  }

  .live-markdown-editor :global(.cm-live-emphasis) {
    font-style: italic;
  }

  .live-markdown-editor :global(.cm-live-inline-code) {
    padding: 0.08rem 0.36rem;
    border-radius: 0.35rem;
    background-color: var(--element-bg);
    font-family: var(--font-mono);
    font-size: 0.92em;
  }

  .live-markdown-editor :global(.cm-live-frontmatter-line) {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--fg-muted);
  }

  .live-markdown-editor :global(.cm-live-code-line) {
    font-family: var(--font-mono);
    font-size: 12px;
    background-color: color-mix(in srgb, var(--element-bg) 85%, transparent);
  }
</style>