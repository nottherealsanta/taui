<!--
  4.11 MonacoEditor.svelte
  Reusable Monaco Editor wrapper for Svelte 5.
  Handles create/dispose lifecycle, ResizeObserver, theme switching.

  Props:
    value       — content to display
    language    — Monaco language id (default 'plaintext')
    readOnly    — default true
    lineStart   — real file line number for the first displayed line (gutter offset)
    diffOrig    — original content for diff mode (activates diff editor)
    theme       — override theme name; defaults to current Taui theme
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { theme as themeStore } from '$stores/theme.svelte'
  import { registerMonacoThemes, monacoThemeName } from '$services/monaco-theme'
  import type * as Monaco from 'monaco-editor'

  interface Props {
    value: string
    language?: string
    readOnly?: boolean
    lineStart?: number
    diffOrig?: string | null
    themeName?: string | null
  }

  const {
    value,
    language = 'plaintext',
    readOnly = true,
    lineStart = 1,
    diffOrig = null,
    themeName = null,
  }: Props = $props()

  let container: HTMLElement | undefined = $state()
  let editor: Monaco.editor.IStandaloneCodeEditor | Monaco.editor.IStandaloneDiffEditor | null = null
  let monaco: typeof Monaco | null = null
  let resizeObs: ResizeObserver | null = null

  // Determine active theme
  const activeTheme = $derived(themeName ?? monacoThemeName(themeStore.isDark))

  onMount(async () => {
    // Lazy-load Monaco to avoid blocking initial page load.
    monaco = await import('monaco-editor')
    registerMonacoThemes(monaco)

    if (!container) return

    const commonOptions: Monaco.editor.IEditorOptions & Monaco.editor.IGlobalEditorOptions = {
      readOnly,
      minimap: { enabled: readOnly },
      scrollBeyondLastLine: false,
      wordWrap: 'on',
      folding: true,
      renderLineHighlight: readOnly ? 'none' : 'line',
      automaticLayout: false, // we manage via ResizeObserver
      fontFamily: '"JetBrains Mono", monospace',
      fontSize: 12,
      lineHeight: 18,
      padding: { top: 8, bottom: 8 },
      theme: activeTheme,
    }

    if (diffOrig !== null) {
      // Diff editor mode
      const diffEditor = monaco.editor.createDiffEditor(container, {
        ...commonOptions,
        renderSideBySide: true,
        originalEditable: false,
      })
      diffEditor.setModel({
        original: monaco.editor.createModel(diffOrig, language),
        modified: monaco.editor.createModel(value, language),
      })
      editor = diffEditor
    } else {
      // Standard editor mode
      const stdEditor = monaco.editor.create(container, {
        ...commonOptions,
        value,
        language,
        lineNumbers: lineStart > 1
          ? (n: number) => String(n + lineStart - 1)
          : 'on',
      })
      editor = stdEditor
    }

    // ResizeObserver for responsive layout
    resizeObs = new ResizeObserver(() => editor?.layout())
    resizeObs.observe(container)
  })

  onDestroy(() => {
    resizeObs?.disconnect()
    editor?.dispose()
    editor = null
  })

  // React to value changes
  $effect(() => {
    if (!editor || !monaco) return
    if (diffOrig !== null) {
      const diffEditor = editor as Monaco.editor.IStandaloneDiffEditor
      const model = diffEditor.getModel()
      if (model) {
        if (model.modified.getValue() !== value) model.modified.setValue(value)
        if (diffOrig !== null && model.original.getValue() !== diffOrig) model.original.setValue(diffOrig)
      }
    } else {
      const stdEditor = editor as Monaco.editor.IStandaloneCodeEditor
      const model = stdEditor.getModel()
      if (model && model.getValue() !== value) {
        model.setValue(value)
      }
    }
  })

  // React to theme changes
  $effect(() => {
    if (!monaco) return
    monaco.editor.setTheme(activeTheme)
  })
</script>

<div class="monaco-container" bind:this={container}></div>

<style lang="postcss">
  .monaco-container {
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
</style>
