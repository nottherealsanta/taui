<!--
  TangleTreePane.svelte — Phase 5 primary view.

  Assembles:
    • TreeView (virtual-scrolled, keyboard nav, inline editing)
    • QuestionOverlay for any pending agent questions on visible nodes
    • MetadataRow below the selected node (verification, depends_on, related_to)
    • code_ref sub-rows are rendered inline in the tree via TreeView → CodeRefRow
    • Fold state persistence via watchFoldState()

  Slots / events (via callback props):
    onshowCode   — code preview selected; parent shows BottomDrawer
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import TreeView from '$components/TreeView.svelte'
  import QuestionOverlay from '$components/QuestionOverlay.svelte'
  import MetadataRow from '$components/MetadataRow.svelte'
  import { appState } from '$stores/app-state.svelte'
  import { dispatch } from '$stores/actions'
  import { watchFoldState } from '$services/fold-state'

  interface CodePreview {
    specRef?: string | null
    filePath: string
    content: string
    lineStart: number | null
    lineEnd: number | null
    language?: string
    truncated?: boolean
    previewStart?: number | null
    previewEnd?: number | null
  }

  interface Props {
    onshowCode?: (preview: CodePreview) => void
  }
  const { onshowCode }: Props = $props()

  // ── Fold state watcher ─────────────────────────────────────────────────────
  let stopFoldWatch: (() => void) | null = null
  onMount(() => { stopFoldWatch = watchFoldState() })
  onDestroy(() => stopFoldWatch?.())

  // ── Pending question for selected node ─────────────────────────────────────
  const selectedQuestion = $derived(
    appState.selectedSpecRef !== null
      ? appState.pendingQuestions.find(
          (q) => q.questionNodeRef === appState.selectedSpecRef
        ) ?? null
      : null
  )

  // ── Code ref handler ───────────────────────────────────────────────────────
  function handleShowCodeRef(
    filePath: string,
    content: string,
    lineStart: number | null,
    lineEnd: number | null,
    language?: string,
    specRef?: string | null,
    truncated?: boolean,
    previewStart?: number | null,
    previewEnd?: number | null,
  ) {
    onshowCode?.({ specRef, filePath, content, lineStart, lineEnd, language, truncated, previewStart, previewEnd })
  }

  // ── Double-click on a tree row → enter editing ─────────────────────────────
  function handleEnterEditing(nodeId: number) {
    dispatch({ type: 'selectNode', nodeId })
    dispatch({ type: 'enterEditing' })
  }
</script>

<div class="tangle-tree-pane">
  <!-- Tree view fills remaining space -->
  <div class="tree-scroll-area">
    <TreeView onenterEditing={handleEnterEditing} onshowCodeRef={handleShowCodeRef} />
  </div>

  <!-- Selected node extras (question overlay + metadata) -->
  {#if appState.selectedNode !== null}
    <div class="node-extras">
      {#if selectedQuestion !== null}
        <QuestionOverlay question={selectedQuestion} />
      {/if}

      <MetadataRow
        nodeId={appState.selectedNode}
      />
    </div>
  {/if}
</div>

<style lang="postcss">
  .tangle-tree-pane {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  .tree-scroll-area {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    position: relative;
  }

  .node-extras {
    flex-shrink: 0;
    border-top: 1px solid var(--border-variant);
    background-color: var(--bg-surface);
    max-height: 240px;
    overflow-y: auto;
  }
</style>
