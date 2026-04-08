<!--
  CodeRefRow.svelte
  A code_ref sub-row rendered in the tree below its parent node.
  Shows a file icon + ref path; click fetches and shows the code preview.
-->
<script lang="ts">
  import type { FlatNode } from '$types/index'
  import { indentPx } from '$types/typography'
  import { appState } from '$stores/app-state.svelte'
  import { backendClient } from '$services/backend-client'

  interface Props {
    node: FlatNode
    onshowCodeRef?: (
      filePath: string,
      content: string,
      lineStart: number | null,
      lineEnd: number | null,
      language?: string,
      specRef?: string | null,
      truncated?: boolean,
      previewStart?: number | null,
      previewEnd?: number | null,
    ) => void
  }
  const { node, onshowCodeRef }: Props = $props()

  const indent = $derived(indentPx(node.depth))
  const refValue = $derived(node.codeRefValue ?? '')
  const parentNode = $derived(node.parentNodeId !== undefined ? appState.nodes[node.parentNodeId] : null)

  let loading = $state(false)

  // Derive a short display label from the raw ref (strip backtick formatting if present).
  const displayLabel = $derived(refValue.replace(/^\{\{code_ref:\s*`?|`?\}\}$/g, ''))

  const langMap: Record<string, string> = {
    rs: 'rust', ts: 'typescript', tsx: 'typescript', js: 'javascript',
    jsx: 'javascript', py: 'python', json: 'json', yaml: 'yaml', yml: 'yaml',
    md: 'markdown', html: 'html', css: 'css', toml: 'toml', sh: 'shell',
  }

  async function handleClick() {
    if (!parentNode || loading) return
    loading = true
    try {
      const result = await backendClient.getNodeCodeRefs(parentNode.specRef, 200)
      const preview = result.refs.find((r) => r.rawRef === refValue)
      if (preview && !preview.error) {
        const ext = preview.filePath.split('.').pop()?.toLowerCase() ?? ''
        onshowCodeRef?.(
          preview.filePath,
          preview.content,
          preview.lineStart,
          preview.lineEnd,
          langMap[ext] ?? 'plaintext',
          parentNode.specRef,
          preview.truncated,
          preview.previewStart,
          preview.previewEnd,
        )
      }
    } catch (e) {
      console.error('[CodeRefRow] fetch failed', e)
    } finally {
      loading = false
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="code-ref-row"
  class:loading
  style:padding-left="{indent + 4}px"
  onclick={handleClick}
  role="button"
  tabindex="-1"
  title={refValue}
>
  <span class="ref-icon">⟨/⟩</span>
  <span class="ref-label">{displayLabel}</span>
  {#if loading}
    <span class="loading-dot"></span>
  {/if}
</div>

<style lang="postcss">
  .code-ref-row {
    display: flex;
    align-items: center;
    gap: 5px;
    height: 28px;
    padding-right: 8px;
    cursor: pointer;
    border-radius: 4px;
    margin: 1px 4px;
    color: var(--fg-muted);
    font-size: 11px;
    transition: background-color 0.1s, color 0.1s;
  }

  .code-ref-row:hover {
    background-color: var(--element-hover);
    color: var(--fg-secondary);
  }

  .code-ref-row.loading {
    opacity: 0.6;
    cursor: wait;
  }

  .ref-icon {
    flex-shrink: 0;
    font-size: 9px;
    opacity: 0.6;
    font-family: var(--font-mono);
    letter-spacing: -1px;
  }

  .ref-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: 10px;
  }

  .loading-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background-color: var(--fg-accent);
    animation: pulse 1s ease-in-out infinite;
    flex-shrink: 0;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
</style>
