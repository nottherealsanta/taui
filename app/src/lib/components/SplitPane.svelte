<!--
  SplitPane.svelte — Resizable panel divider.

  Renders two snippets side-by-side (horizontal) or top-and-bottom (vertical)
  separated by a draggable gutter. Stores widths in localStorage.

  Props:
    direction    — 'horizontal' | 'vertical'
    initialSize  — starting size (px) of the first panel
    initialRatio — starting size as a fraction of the container when no saved size exists
    minSize      — minimum size for the first panel
    maxSize      — maximum size for the first panel
    minSecondSize — minimum size for the second panel
    storageKey   — localStorage key for persisting the size
    collapsed    — if true, the first panel is fully collapsed (0px)
    first        — snippet for the first pane
    second       — snippet for the second pane
-->
<script lang="ts">
  import type { Snippet } from 'svelte'
  import { onMount } from 'svelte'

  interface Props {
    direction?: 'horizontal' | 'vertical'
    initialSize?: number
    initialRatio?: number | null
    minSize?: number
    maxSize?: number
    minSecondSize?: number
    storageKey?: string | null
    collapsed?: boolean
    first: Snippet
    second: Snippet
  }

  const {
    direction = 'horizontal',
    initialSize = 250,
    initialRatio = null,
    minSize = 120,
    maxSize = 600,
    minSecondSize = 120,
    storageKey = null,
    collapsed = false,
    first,
    second,
  }: Props = $props()

  let containerEl: HTMLElement | undefined = $state()
  let size = $state(250)
  let dragging = $state(false)

  function containerExtent(): number {
    if (!containerEl) return initialSize
    const rect = containerEl.getBoundingClientRect()
    return direction === 'horizontal' ? rect.width : rect.height
  }

  function clampSize(nextSize: number): number {
    const extent = containerExtent()
    const maxAllowed = Math.min(maxSize, Math.max(minSize, extent - minSecondSize))
    return Math.max(minSize, Math.min(maxAllowed, nextSize))
  }

  function defaultSizeFromContainer(): number {
    const extent = containerExtent()
    if (initialRatio !== null) {
      return clampSize(extent * initialRatio)
    }
    return clampSize(initialSize)
  }

  // Restore from localStorage
  onMount(() => {
    size = defaultSizeFromContainer()
    if (storageKey) {
      try {
        const stored = localStorage.getItem(storageKey)
        if (stored) {
          const parsed = parseInt(stored, 10)
          if (!isNaN(parsed)) {
            size = clampSize(parsed)
          }
        }
      } catch {
        // ignore
      }
    }

    if (!containerEl) return
    const observer = new ResizeObserver(() => {
      size = clampSize(size)
    })
    observer.observe(containerEl)
    return () => observer.disconnect()
  })

  // Persist to localStorage on change
  $effect(() => {
    if (storageKey && !collapsed) {
      try {
        localStorage.setItem(storageKey, String(size))
      } catch {
        // ignore
      }
    }
  })

  function handlePointerDown(e: PointerEvent) {
    if (collapsed) return
    e.preventDefault()
    dragging = true
    const target = e.currentTarget as HTMLElement
    target.setPointerCapture(e.pointerId)
  }

  function handlePointerMove(e: PointerEvent) {
    if (!dragging || collapsed) return
    e.preventDefault()

    const gutterEl = e.currentTarget as HTMLElement
    const container = gutterEl.parentElement
    if (!container) return

    const rect = container.getBoundingClientRect()

    let newSize: number
    if (direction === 'horizontal') {
      newSize = e.clientX - rect.left
    } else {
      newSize = e.clientY - rect.top
    }

    size = clampSize(newSize)
  }

  function handlePointerUp() {
    dragging = false
  }

  const displaySize = $derived(collapsed ? 0 : size)
</script>

<div
  class="split-pane"
  class:horizontal={direction === 'horizontal'}
  class:vertical={direction === 'vertical'}
  class:dragging
  bind:this={containerEl}
>
  <div
    class="pane first-pane"
    style="{direction === 'horizontal' ? 'width' : 'height'}: {displaySize}px; {collapsed ? 'overflow: hidden;' : ''}"
  >
    {#if !collapsed}
      {@render first()}
    {/if}
  </div>

  {#if !collapsed}
    <div
      class="gutter"
      role="separator"
      aria-orientation={direction}
      onpointerdown={handlePointerDown}
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
      onpointercancel={handlePointerUp}
    ></div>
  {/if}

  <div class="pane second-pane">
    {@render second()}
  </div>
</div>

<style lang="postcss">
  .split-pane {
    display: flex;
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
  }

  .split-pane.horizontal {
    flex-direction: row;
  }

  .split-pane.vertical {
    flex-direction: column;
  }

  .pane {
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .first-pane {
    flex-shrink: 0;
  }

  .second-pane {
    flex: 1;
    min-width: 0;
    min-height: 0;
  }

  .gutter {
    flex-shrink: 0;
    background-color: var(--border-variant);
    transition: background-color 0.15s;
    z-index: 10;
  }

  .horizontal > .gutter {
    width: 1px;
    cursor: col-resize;
  }

  .vertical > .gutter {
    height: 1px;
    cursor: row-resize;
  }

  .gutter:hover,
  .dragging > .gutter {
    background-color: var(--fg-accent);
  }

  /* Prevent text selection during drag */
  .dragging {
    user-select: none;
  }
</style>
