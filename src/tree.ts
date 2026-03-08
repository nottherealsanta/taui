import { State, visibleNodes } from './state';
import { NodeEditorState } from './editors';

export interface CodeReferencePreview {
  raw_ref: string;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  preview_start: number | null;
  preview_end: number | null;
  content: string;
  truncated: boolean;
  error?: string;
}

export interface NodeCodeReferenceState {
  loading: boolean;
  error: string | null;
  refs: CodeReferencePreview[];
}

export interface TreeRenderCallbacks {
  onSelect: (nodeId: number) => void;
  onToggleFold: (nodeId: number) => void;
  getEditorContainer: (specRef: string) => HTMLElement | null;
  registerEditorContainer: (specRef: string, container: HTMLElement) => void;
  getEditorState: (specRef: string) => NodeEditorState | undefined;
  getCodeReferenceState: (specRef: string) => NodeCodeReferenceState | undefined;
}

export function renderTree({
  state,
  treeElement,
  callbacks,
}: {
  state: State;
  treeElement: HTMLElement;
  callbacks: TreeRenderCallbacks;
}) {
  const flat = visibleNodes(state);
  const baseDepth = flat.length > 0 ? Math.min(...flat.map((node) => node.depth)) : 1;
  treeElement.replaceChildren();

  if (flat.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'tree-empty';
    empty.textContent = 'No spec nodes found.';
    treeElement.append(empty);
    return;
  }

  for (const node of flat) {
    const displayDepth = Math.max(0, node.depth - baseDepth);
    const row = document.createElement('article');
    row.className = 'spec-row';
    if (node.id === state.selectedNodeId) {
      row.classList.add('selected');
    }
    row.addEventListener('click', (event) => {
      const target = event.target as HTMLElement;
      if (
        target.closest('.fold-toggle') ||
        target.closest('.inline-editor-wrapper') ||
        target.closest('.code-ref-panel')
      ) {
        return;
      }
      callbacks.onSelect(node.id);
    });

    const header = document.createElement('div');
    header.className = 'node-header';
    header.style.paddingLeft = `${displayDepth * 18}px`;

    if (node.children.length > 0) {
      const chevron = document.createElement('button');
      chevron.type = 'button';
      chevron.className = `fold-toggle ${node.collapsed ? 'collapsed' : 'expanded'}`;
      chevron.textContent = node.collapsed ? '▸' : '▾';
      chevron.addEventListener('click', (event) => {
        event.stopPropagation();
        callbacks.onToggleFold(node.id);
      });
      header.append(chevron);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'fold-spacer';
      header.append(spacer);
    }

    const meta = document.createElement('div');
    meta.className = 'node-meta';
    const specRef = document.createElement('div');
    specRef.className = 'spec-ref';
    specRef.textContent = node.spec_ref;
    meta.append(specRef);
    header.append(meta);

    const status = document.createElement('span');
    status.className = `status status-${node.status.replace(/-/g, '')}`;
    status.textContent = node.status;
    header.append(status);

    row.append(header);

    const editorWrapper = document.createElement('div');
    editorWrapper.className = 'inline-editor-wrapper';

    let editorContainer = callbacks.getEditorContainer(node.spec_ref);
    if (!editorContainer) {
      editorContainer = document.createElement('div');
      editorContainer.className = 'inline-editor-container';
      editorContainer.dataset.specRef = node.spec_ref;
      callbacks.registerEditorContainer(node.spec_ref, editorContainer);
    }

    editorWrapper.append(editorContainer);

    const editorState = callbacks.getEditorState(node.spec_ref);
    if (editorState?.error) {
      const errorDiv = document.createElement('div');
      errorDiv.className = 'editor-error';
      errorDiv.textContent = editorState.error;
      editorWrapper.append(errorDiv);
    }

    if (editorState?.saving) {
      const savingDiv = document.createElement('div');
      savingDiv.className = 'editor-saving-indicator';
      savingDiv.textContent = 'Saving...';
      editorWrapper.append(savingDiv);
    }

    row.append(editorWrapper);

    const codeRefState = callbacks.getCodeReferenceState(node.spec_ref);
    if (codeRefState && (codeRefState.loading || codeRefState.error || codeRefState.refs.length > 0)) {
      const panel = document.createElement('section');
      panel.className = 'code-ref-panel';

      const panelHeader = document.createElement('div');
      panelHeader.className = 'code-ref-header';
      panelHeader.textContent = 'Code References';
      panel.append(panelHeader);

      if (codeRefState.loading) {
        const loading = document.createElement('div');
        loading.className = 'code-ref-loading';
        loading.textContent = 'Loading code references...';
        panel.append(loading);
      }

      if (codeRefState.error) {
        const error = document.createElement('div');
        error.className = 'code-ref-error';
        error.textContent = codeRefState.error;
        panel.append(error);
      }

      for (const ref of codeRefState.refs) {
        const refCard = document.createElement('article');
        refCard.className = 'code-ref-card';

        const refMeta = document.createElement('div');
        refMeta.className = 'code-ref-meta';
        const rangeText = formatRange(ref);
        refMeta.textContent = `${ref.file_path}${rangeText ? ` (${rangeText})` : ''}`;
        refCard.append(refMeta);

        if (ref.error) {
          const refError = document.createElement('div');
          refError.className = 'code-ref-error';
          refError.textContent = ref.error;
          refCard.append(refError);
        } else {
          const pre = document.createElement('pre');
          pre.className = 'code-ref-content';
          pre.setAttribute('aria-readonly', 'true');
          pre.textContent = ref.content || '// Empty selection';
          refCard.append(pre);

          if (ref.truncated) {
            const truncation = document.createElement('div');
            truncation.className = 'code-ref-truncated';
            truncation.textContent = 'Snippet truncated';
            refCard.append(truncation);
          }
        }

        panel.append(refCard);
      }

      row.append(panel);
    }

    treeElement.append(row);
  }
}

function formatRange(ref: CodeReferencePreview): string {
  if (ref.preview_start == null || ref.preview_end == null) {
    return '';
  }
  if (ref.preview_start === ref.preview_end) {
    return `L${ref.preview_start}`;
  }
  return `L${ref.preview_start}-L${ref.preview_end}`;
}
