<!--
  4.4 InlineEditor.svelte
  Plain textarea for editing the active node's markdown.
  Phase 5 wires this into the spec tree; Milkdown can be swapped in later.
  Saves via spec/updateNode on blur or node-switch.
  Escape cancels (restores original). Enter (without Shift) done in selection mode.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'
  import { backendClient } from '$services/backend-client'

  interface Props {
    nodeId: number
    specRef: string
    initialMarkdown: string
    onsave?: (markdown: string) => void
    oncancel?: () => void
  }
  const { nodeId, specRef, initialMarkdown, onsave, oncancel }: Props = $props()

  let textarea: HTMLTextAreaElement | undefined = $state()
  let value = $state(initialMarkdown)
  let saving = $state(false)

  onMount(async () => {
    await tick()
    if (textarea) {
      textarea.focus()
      // Place cursor at end
      textarea.setSelectionRange(value.length, value.length)
      autoResize()
    }
  })

  function autoResize() {
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = textarea.scrollHeight + 'px'
  }

  async function save() {
    if (saving) return
    const trimmed = value.trim()
    saving = true
    try {
      // Update local state immediately
      if (appState.nodes[nodeId]) {
        appState.nodes[nodeId].markdown = trimmed
      }
      // Persist to backend
      if (specRef && !specRef.startsWith('local/')) {
        await backendClient.updateNode(specRef, trimmed)
      }
      onsave?.(trimmed)
    } catch (e) {
      console.error('[InlineEditor] save failed:', e)
    } finally {
      saving = false
    }
  }

  function cancel() {
    if (appState.nodes[nodeId]) {
      appState.nodes[nodeId].markdown = initialMarkdown
    }
    oncancel?.()
    dispatch({ type: 'exitEditing' })
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      cancel()
    } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      // Single Enter → finish editing, stay on node
      e.preventDefault()
      save().then(() => dispatch({ type: 'exitEditing' }))
    }
    // Prevent tree-level key handlers from firing while editor is focused
    e.stopPropagation()
  }

  function handleBlur() {
    if (appState.editorMode === 'editing') {
      save().then(() => dispatch({ type: 'exitEditing' }))
    }
  }

  function handleInput() {
    autoResize()
  }
</script>

<div class="inline-editor" class:saving>
  <textarea
    bind:this={textarea}
    bind:value
    class="editor-textarea selectable"
    rows="1"
    spellcheck="false"
    autocomplete="off"
    autocorrect="off"
    autocapitalize="off"
    onkeydown={handleKeydown}
    onblur={handleBlur}
    oninput={handleInput}
  ></textarea>
  {#if saving}
    <span class="saving-indicator">saving…</span>
  {/if}
</div>

<style lang="postcss">
  .inline-editor {
    display: flex;
    flex-direction: column;
    width: 100%;
    position: relative;
  }

  .editor-textarea {
    width: 100%;
    min-height: 24px;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--fg-accent);
    outline: none;
    resize: none;
    overflow: hidden;
    font-family: var(--font-sans);
    font-size: inherit;
    font-weight: inherit;
    color: var(--fg-primary);
    line-height: 1.4;
    padding: 0;
    box-sizing: border-box;
  }

  .saving-indicator {
    font-size: 10px;
    color: var(--fg-muted);
    position: absolute;
    bottom: -16px;
    right: 0;
  }

  .saving .editor-textarea {
    opacity: 0.6;
  }
</style>
