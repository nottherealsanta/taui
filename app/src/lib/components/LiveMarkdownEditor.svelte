<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Editor } from '@tiptap/core'
  import StarterKit from '@tiptap/starter-kit'
  import { Table, TableRow, TableCell, TableHeader } from '@tiptap/extension-table'
  import { Image } from '@tiptap/extension-image'
  import { Link } from '@tiptap/extension-link'
  import { TaskList } from '@tiptap/extension-task-list'
  import { TaskItem } from '@tiptap/extension-task-item'
  import { CodeBlockLowlight } from '@tiptap/extension-code-block-lowlight'
  import { Markdown } from '@tiptap/markdown'
  import { common, createLowlight } from 'lowlight'
  import { DisclosureList } from '$lib/extensions/disclosure-list'
  import { CodeRefDecorations } from '$lib/extensions/code-ref-decorations'
  import CodeFileModal from '$components/CodeFileModal.svelte'
  import { backendClient } from '$services/backend-client'
  import { tabStore } from '$stores/tabs.svelte'
  import {
    inferLanguage,
    readCodeRefFromDataset,
    resolveCodeRef,
    type ParsedCodeRef,
  } from '$lib/utils/code-refs'

  interface Props {
    content: string
    filePath: string
    tabId: string
    readOnly?: boolean
  }

  const { content, filePath, tabId, readOnly = false }: Props = $props()

  let editorEl: HTMLDivElement | undefined = $state()
  let editor: Editor | null = null
  let applyingExternalContent = false

  type ModalState = {
    filePath: string
    target: string | null
    snippetContent: string | null
    fullFileContent: string | null
    language: string | null
    lineStart: number | null
    lineEnd: number | null
    loading: boolean
    error: string | null
    emptyMessage: string | null
  }

  let codeModal: ModalState | null = $state(null)

  const lowlight = createLowlight(common)

  function resolveHref(href: string): string {
    if (href.startsWith('http://') || href.startsWith('https://')) return href
    const dir = filePath.substring(0, filePath.lastIndexOf('/') + 1)
    return dir + href
  }

  function saveCurrentTab(): void {
    void tabStore.save(tabId)
  }

  async function openCodeRefModal(ref: ParsedCodeRef): Promise<void> {
    codeModal = {
      filePath: ref.filePath,
      target: ref.target,
      snippetContent: null,
      fullFileContent: null,
      language: inferLanguage(ref.filePath),
      lineStart: null,
      lineEnd: null,
      loading: true,
      error: null,
      emptyMessage: null,
    }

    try {
      const [fullFile, resolved] = await Promise.all([
        backendClient.readFile(ref.filePath).catch(() => null),
        resolveCodeRef(ref).catch(() => null),
      ])

      // Normalize content: treat empty strings as null
      const snippetContent = resolved?.content?.trim() ? resolved.content : null
      const fullFileContent = fullFile?.content?.trim() ? fullFile.content : null

      // Only show "No preview available" if BOTH are unavailable
      if (!snippetContent && !fullFileContent) {
        codeModal = {
          filePath: ref.filePath,
          target: ref.target,
          snippetContent: null,
          fullFileContent: null,
          language: inferLanguage(ref.filePath),
          lineStart: null,
          lineEnd: null,
          loading: false,
          error: null,
          emptyMessage: 'No preview available',
        }
        return
      }

      codeModal = {
        filePath: ref.filePath,
        target: ref.target,
        snippetContent,
        fullFileContent,
        language: resolved?.language ?? inferLanguage(ref.filePath),
        // Only set line range if we have actual snippet content
        lineStart: snippetContent ? (resolved?.resolvedStart ?? null) : null,
        lineEnd: snippetContent ? (resolved?.resolvedEnd ?? null) : null,
        loading: false,
        error: null,
        emptyMessage: null,
      }
    } catch (error) {
      codeModal = {
        filePath: ref.filePath,
        target: ref.target,
        snippetContent: null,
        fullFileContent: null,
        language: inferLanguage(ref.filePath),
        lineStart: null,
        lineEnd: null,
        loading: false,
        error: null,
        emptyMessage: 'No preview available',
      }
    }
  }

  function handleModalClose(): void {
    codeModal = null
  }

  function handleOpenCodeRefEvent(event: Event): void {
    const customEvent = event as CustomEvent<ParsedCodeRef>
    if (!customEvent.detail) return
    void openCodeRefModal(customEvent.detail)
  }

  function handleEditorClick(event: MouseEvent): void {
    const target = event.target as HTMLElement | null
    const codeRefEl = target?.closest<HTMLElement>('.code-ref-chip, .code-ref-inline-preview')
    if (!codeRefEl) return

    const ref = readCodeRefFromDataset(codeRefEl)
    if (!ref) return

    event.preventDefault()
    event.stopPropagation()
    void openCodeRefModal(ref)
  }

  function getMarkdownFromEditor(): string {
    if (!editor) return content
    const storage = editor.storage['markdown'] as
      | { manager?: { serialize: (content: any) => string } }
      | undefined
    if (storage?.manager) {
      return storage.manager.serialize(editor.state.doc)
    }
    return editor.getText()
  }

  onMount(() => {
    if (!editorEl) return

    window.addEventListener('taui:open-code-ref', handleOpenCodeRefEvent as EventListener)
    editorEl.addEventListener('click', handleEditorClick)

    editor = new Editor({
      element: editorEl,
      editable: !readOnly,
      // Don't pass content here — it won't be parsed as markdown
      // We'll set it after creation with contentType: 'markdown'
      extensions: [
        Markdown,
        StarterKit.configure({
          codeBlock: false, // replaced by CodeBlockLowlight
        }),
        CodeBlockLowlight.configure({
          lowlight,
        }),
        Table.configure({
          resizable: false,
          HTMLAttributes: { class: 'tiptap-table' },
        }),
        TableRow,
        TableCell,
        TableHeader,
        Image.configure({
          inline: true,
        }),
        Link.configure({
          openOnClick: false,
          HTMLAttributes: { class: 'tiptap-link' },
        }),
        TaskList,
        TaskItem.configure({
          nested: true,
        }),
        DisclosureList,
        CodeRefDecorations,
      ],
      onUpdate: ({ editor: ed }) => {
        if (applyingExternalContent) return
        const md = getMarkdownFromEditor()
        tabStore.updateContent(tabId, md)
      },
      editorProps: {
        handleKeyDown: (_view, event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 's') {
            event.preventDefault()
            saveCurrentTab()
            return true
          }
          return false
        },
        handleClick: (_view, _pos, event) => {
          const target = event.target as HTMLElement
          const codeRefEl = target.closest<HTMLElement>('.code-ref-chip, .code-ref-inline-preview')
          if (codeRefEl) {
            const ref = readCodeRefFromDataset(codeRefEl)
            if (!ref) return false
            event.preventDefault()
            void openCodeRefModal(ref)
            return true
          }

          const linkEl = target.closest('a')
          if (!linkEl) return false
          const href = linkEl.getAttribute('href')
          if (!href) return false

          event.preventDefault()
          const resolved = resolveHref(href)
          if (resolved.startsWith('http://') || resolved.startsWith('https://')) {
            window.open(resolved, '_blank', 'noopener')
          } else {
            void tabStore.openFile(resolved)
          }
          return true
        },
      },
    })

    // Parse initial markdown content after editor is created
    if (content) {
      applyingExternalContent = true
      editor.commands.setContent(content, { contentType: 'markdown' })
      applyingExternalContent = false
    }

  })

  // Sync external content changes (e.g. revert, external file change)
  $effect(() => {
    if (!editor) return
    const currentMd = getMarkdownFromEditor()
    if (currentMd !== content) {
      applyingExternalContent = true
      editor.commands.setContent(content, { contentType: 'markdown' })
      applyingExternalContent = false
    }
  })

  onDestroy(() => {
    window.removeEventListener('taui:open-code-ref', handleOpenCodeRefEvent as EventListener)
    editorEl?.removeEventListener('click', handleEditorClick)
    editor?.destroy()
    editor = null
  })
</script>

<div class="live-markdown-editor selectable" bind:this={editorEl}></div>

{#if codeModal}
  <CodeFileModal
    filePath={codeModal.filePath}
    target={codeModal.target}
    snippetContent={codeModal.snippetContent}
    fullFileContent={codeModal.fullFileContent}
    language={codeModal.language}
    lineStart={codeModal.lineStart}
    lineEnd={codeModal.lineEnd}
    loading={codeModal.loading}
    error={codeModal.error}
    emptyMessage={codeModal.emptyMessage}
    onclose={handleModalClose}
  />
{/if}

<style lang="postcss">
  .live-markdown-editor {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    position: relative;
  }

  /* ─── TipTap Prose Styling ─────────────────────────────────────────────────── */
  .live-markdown-editor :global(.tiptap) {
    height: 100%;
    overflow: auto;
    padding: 20px 24px 56px;
    max-width: var(--max-content-width);
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.7;
    color: var(--fg-primary);
    background-color: var(--bg-surface);
    outline: none;
    caret-color: var(--fg-accent);
  }

  .live-markdown-editor :global(.tiptap:focus) {
    outline: none;
  }

  /* ── Headings ── */
  .live-markdown-editor :global(.tiptap h1) {
    font-size: 2rem;
    line-height: 1.2;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 1.5em 0 0.5em;
  }

  .live-markdown-editor :global(.tiptap h1:first-child) {
    margin-top: 0;
  }

  .live-markdown-editor :global(.tiptap h2) {
    font-size: 1.6rem;
    line-height: 1.25;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 1.4em 0 0.4em;
  }

  .live-markdown-editor :global(.tiptap h3) {
    font-size: 1.35rem;
    line-height: 1.3;
    font-weight: 600;
    margin: 1.2em 0 0.3em;
  }

  .live-markdown-editor :global(.tiptap h4),
  .live-markdown-editor :global(.tiptap h5),
  .live-markdown-editor :global(.tiptap h6) {
    font-size: 1.1rem;
    line-height: 1.35;
    font-weight: 600;
    margin: 1em 0 0.2em;
  }

  /* ── Paragraphs ── */
  .live-markdown-editor :global(.tiptap p) {
    margin: 0.6em 0;
  }

  /* ── Strong / Emphasis ── */
  .live-markdown-editor :global(.tiptap strong) {
    font-weight: 700;
  }

  .live-markdown-editor :global(.tiptap em) {
    font-style: italic;
  }

  .live-markdown-editor :global(.tiptap s) {
    text-decoration: line-through;
    text-decoration-color: var(--fg-muted);
  }

  /* ── Inline Code ── */
  .live-markdown-editor :global(.tiptap code) {
    padding: 0.08rem 0.36rem;
    background-color: var(--element-bg);
    font-family: var(--font-mono);
    font-size: 0.88em;
  }

  .live-markdown-editor :global(.tiptap code:has(.code-ref-chip)) {
    padding: 0;
    background: transparent;
  }

  .live-markdown-editor :global(.tiptap .code-ref-chip) {
    display: inline-flex;
    align-items: center;
    padding: 0.18rem 0.44rem;
    margin: 0 0.04rem;
    border: 1px solid var(--border);
    background: var(--bg-surface);
    color: var(--fg-secondary);
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    white-space: nowrap;
  }

  .live-markdown-editor :global(.tiptap .code-ref-chip:hover) {
    border-color: var(--fg-muted);
    background: var(--bg-elevated);
    color: var(--fg-primary);
  }

  .live-markdown-editor :global(.tiptap .code-ref-standalone-paragraph) {
    margin-bottom: 0.3rem;
  }

  .live-markdown-editor :global(.tiptap .code-ref-standalone-paragraph .code-ref-chip) {
    font-size: 0.92em;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview) {
    margin: 0.45rem 0 1rem;
    padding: 0.65rem 0.8rem;
    border: 1px solid var(--border);
    background: var(--bg-surface);
    cursor: pointer;
    overflow: hidden;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview:hover) {
    border-color: var(--fg-muted);
    background: var(--bg-elevated);
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview__header) {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.55rem;
    min-width: 0;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview__badge) {
    padding: 0.14rem 0.36rem;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--fg-muted);
    font-family: var(--font-mono);
    font-size: 10px;
    line-height: 1;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview__title) {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--fg-primary);
    font-family: var(--font-mono);
    font-size: 12px;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview__body) {
    margin: 0;
    padding: 0.72rem 0.8rem;
    border: 1px solid var(--border);
    background: var(--bg-base);
    overflow-x: auto;
    color: var(--fg-primary);
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .live-markdown-editor :global(.tiptap .code-ref-inline-preview__footer) {
    margin-top: 0.5rem;
    color: var(--fg-muted);
    font-size: 11px;
  }

  /* ── Code Block ── */
  .live-markdown-editor :global(.tiptap pre) {
    background-color: color-mix(in srgb, var(--element-bg) 85%, transparent);
    padding: 12px 16px;
    margin: 0.8em 0;
    overflow-x: auto;
  }

  .live-markdown-editor :global(.tiptap pre code) {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.5;
    background: none;
    padding: 0;
    color: var(--fg-primary);
  }

  /* ── Links ── */
  .live-markdown-editor :global(.tiptap a),
  .live-markdown-editor :global(.tiptap .tiptap-link) {
    color: var(--fg-accent);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }

  .live-markdown-editor :global(.tiptap a:hover) {
    opacity: 0.85;
  }

  /* ── Blockquote ── */
  .live-markdown-editor :global(.tiptap blockquote) {
    border-left: 3px solid var(--border);
    padding-left: 16px;
    margin: 0.8em 0;
    color: var(--fg-muted);
    font-style: italic;
  }

  .live-markdown-editor :global(.tiptap blockquote p) {
    margin: 0.3em 0;
  }

  /* ── Lists ── */
  .live-markdown-editor :global(.tiptap ul) {
    padding-left: 24px;
    margin: 0.5em 0;
  }

  .live-markdown-editor :global(.tiptap ol) {
    padding-left: 24px;
    margin: 0.5em 0;
  }

  .live-markdown-editor :global(.tiptap li) {
    margin: 0.15em 0;
  }

  .live-markdown-editor :global(.tiptap li::marker) {
    color: var(--fg-accent);
    font-weight: 700;
  }

  .live-markdown-editor :global(.tiptap ol li::marker) {
    font-variant-numeric: tabular-nums;
    font-size: 0.92em;
  }

  /* ── Task List ── */
  .live-markdown-editor :global(.tiptap ul[data-type="taskList"]) {
    list-style: none;
    padding-left: 8px;
  }

  .live-markdown-editor :global(.tiptap li[data-type="taskItem"]) {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .live-markdown-editor :global(.tiptap li[data-type="taskItem"] input) {
    margin-top: 4px;
    accent-color: var(--fg-accent);
  }

  /* ── Horizontal Rule ── */
  .live-markdown-editor :global(.tiptap hr) {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.5em 0;
  }

  /* ── Image ── */
  .live-markdown-editor :global(.tiptap img) {
    max-width: 100%;
    height: auto;
    margin: 0.5em 0;
  }

  /* ── Table ── */
  .live-markdown-editor :global(.tiptap table) {
    border-collapse: collapse;
    width: auto;
    margin: 1em 0;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.5;
  }

  .live-markdown-editor :global(.tiptap table th) {
    font-weight: 600;
    background-color: color-mix(in srgb, var(--fg-accent) 7%, var(--bg-surface));
    border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
    border-bottom: 2px solid color-mix(in srgb, var(--fg-accent) 30%, var(--border));
    padding: 6px 12px;
    text-align: left;
  }

  .live-markdown-editor :global(.tiptap table td) {
    background-color: color-mix(in srgb, var(--fg-accent) 3%, var(--bg-surface));
    border: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
    padding: 6px 12px;
  }

  .live-markdown-editor :global(.tiptap table tr:hover td) {
    background-color: color-mix(in srgb, var(--fg-accent) 6%, var(--bg-surface));
  }

  /* Table cell selection (TipTap) */
  .live-markdown-editor :global(.tiptap .selectedCell) {
    background-color: var(--element-selected);
  }

  /* ── Selection ── */
  .live-markdown-editor :global(.tiptap ::selection) {
    background-color: var(--element-selected);
  }

  /* ── Syntax highlighting (lowlight) ── */
  .live-markdown-editor :global(.tiptap .hljs-keyword) { color: #c678dd; }
  .live-markdown-editor :global(.tiptap .hljs-string) { color: #98c379; }
  .live-markdown-editor :global(.tiptap .hljs-number) { color: #d19a66; }
  .live-markdown-editor :global(.tiptap .hljs-comment) { color: var(--fg-muted); font-style: italic; }
  .live-markdown-editor :global(.tiptap .hljs-function) { color: #61afef; }
  .live-markdown-editor :global(.tiptap .hljs-title) { color: #61afef; }
  .live-markdown-editor :global(.tiptap .hljs-params) { color: var(--fg-primary); }
  .live-markdown-editor :global(.tiptap .hljs-built_in) { color: #e6c07b; }
  .live-markdown-editor :global(.tiptap .hljs-attr) { color: #d19a66; }
  .live-markdown-editor :global(.tiptap .hljs-literal) { color: #56b6c2; }
  .live-markdown-editor :global(.tiptap .hljs-type) { color: #e6c07b; }
  .live-markdown-editor :global(.tiptap .hljs-meta) { color: var(--fg-muted); }

  /* ── Disclosure (progressive disclosure for headings + lists) ── */

  /* ── List item disclosure ── */

  /* Disclosure list item: position relative so chevron can be placed absolutely */
  .live-markdown-editor :global(.tiptap li.disclosure-item) {
    position: relative;
    list-style: none;
  }

  /* Chevron button — shared base style for both headings and list items */
  .live-markdown-editor :global(.disclosure-chevron) {
    position: absolute;
    left: -22px;
    top: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    padding: 0;
    margin: 0;
    border: none;
    background: none;
    border-radius: 3px;
    color: var(--fg-muted);
    cursor: pointer;
    opacity: 0.6;
    transition: transform 0.15s ease, opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease;
    outline: none;
    transform: rotate(90deg);
  }

  .live-markdown-editor :global(.disclosure-chevron:hover) {
    color: var(--fg-accent);
    opacity: 1;
    background-color: color-mix(in srgb, var(--fg-accent) 10%, transparent);
  }

  .live-markdown-editor :global(.disclosure-chevron.collapsed) {
    transform: rotate(0deg);
  }

  /* ── Heading disclosure ── */

  /* Headings with disclosure get relative positioning for the chevron */
  .live-markdown-editor :global(.tiptap .disclosure-heading) {
    position: relative;
    cursor: default;
  }

  /* Heading chevron — positioned to the left of the heading text */
  .live-markdown-editor :global(.disclosure-heading-chevron) {
    position: absolute;
    left: -26px;
    width: 18px;
    height: 18px;
    opacity: 0.45;
  }

  /* Scale chevron position/size per heading level */
  .live-markdown-editor :global(.tiptap h2.disclosure-heading .disclosure-heading-chevron) {
    top: 8px;
  }

  .live-markdown-editor :global(.tiptap h3.disclosure-heading .disclosure-heading-chevron) {
    top: 6px;
  }

  .live-markdown-editor :global(.tiptap h4.disclosure-heading .disclosure-heading-chevron),
  .live-markdown-editor :global(.tiptap h5.disclosure-heading .disclosure-heading-chevron),
  .live-markdown-editor :global(.tiptap h6.disclosure-heading .disclosure-heading-chevron) {
    top: 4px;
  }

  .live-markdown-editor :global(.disclosure-heading:hover .disclosure-heading-chevron) {
    opacity: 0.8;
  }

  /* Hidden content when parent heading or list item is collapsed */
  .live-markdown-editor :global(.tiptap .disclosure-hidden) {
    display: none;
  }

</style>
