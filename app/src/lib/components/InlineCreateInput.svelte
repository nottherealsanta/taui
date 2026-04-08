<!--
  InlineCreateInput.svelte — Inline text input for creating a new file/folder.
  Shows inside the file tree at the correct depth with auto-focus.
-->
<script lang="ts">
  import { onMount } from 'svelte'

  interface Props {
    isDir: boolean
    depth: number
    oncommit: (name: string) => void
    oncancel: () => void
  }
  const { isDir, depth, oncommit, oncancel }: Props = $props()

  let inputEl: HTMLInputElement | undefined = $state()
  let value = $state('')

  onMount(() => {
    inputEl?.focus()
  })

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (value.trim()) {
        oncommit(value.trim())
      } else {
        oncancel()
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      oncancel()
    }
  }

  function handleBlur() {
    if (value.trim()) {
      oncommit(value.trim())
    } else {
      oncancel()
    }
  }
</script>

<div
  class="inline-create"
  style="padding-left: {12 + depth * 16}px"
>
  <input
    bind:this={inputEl}
    bind:value
    class="create-input"
    placeholder={isDir ? 'folder name' : 'file name'}
    onkeydown={handleKeyDown}
    onblur={handleBlur}
  />
</div>

<style lang="postcss">
  .inline-create {
    display: flex;
    align-items: center;
    gap: 4px;
    padding-top: 2px;
    padding-bottom: 2px;
    padding-right: 8px;
    min-height: 24px;
  }

  .create-input {
    flex: 1;
    min-width: 0;
    background: var(--bg-elevated);
    border: 1px solid var(--accent);
    border-radius: 3px;
    color: var(--fg-primary);
    font-size: 12px;
    padding: 1px 4px;
    outline: none;
    font-family: inherit;
  }

  .create-input::placeholder {
    color: var(--fg-muted);
    opacity: 0.6;
  }
</style>
