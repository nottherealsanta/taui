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
  import { tabStore } from '$stores/tabs.svelte'

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

  const lowlight = createLowlight(common)

  function resolveHref(href: string): string {
    if (href.startsWith('http://') || href.startsWith('https://')) return href
    const dir = filePath.substring(0, filePath.lastIndexOf('/') + 1)
    return dir + href
  }

  function saveCurrentTab(): void {
    void tabStore.save(tabId)
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
    editor?.destroy()
    editor = null
  })
</script>

<div class="live-markdown-editor selectable" bind:this={editorEl}></div>

<style lang="postcss">
  .live-markdown-editor {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
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
</style>
