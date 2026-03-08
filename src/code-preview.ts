import { EditorView, basicSetup } from 'codemirror';
import { EditorState } from '@codemirror/state';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { oneDark } from '@codemirror/theme-one-dark';
import { RpcClient } from './rpc';

export function createCodePreview(container: HTMLElement, rpc?: RpcClient) {
  let view: EditorView | null = null;
  let currentRange: { file_path: string; line_start: number; line_end: number } | null = null;

  async function loadSourceRange(specRef: string, expanded: boolean = false) {
    if (!rpc) return;

    try {
      const result = await rpc.request('spec/getNodeSourceRange', {
        spec_ref: specRef,
        expanded,
        max_lines: 10,
      });

      currentRange = {
        file_path: result.file_path,
        line_start: result.line_start,
        line_end: result.line_end,
      };

      const headerEl = document.getElementById('code-header');
      if (headerEl) {
        headerEl.textContent = `${result.file_path}:${result.preview_start}-${result.preview_end}`;
      }

      const expandBtn = document.getElementById('expand-code-btn');
      if (expandBtn) {
        expandBtn.textContent = result.truncated ? 'Expand' : 'Collapse';
      }

      const content = result.content || '';
      const language = detectLanguage(result.file_path);

      if (view) {
        view.destroy();
      }

      const state = EditorState.create({
        doc: content,
        extensions: [
          basicSetup,
          language,
          oneDark,
          EditorView.editable.of(false),
        ],
      });

      view = new EditorView({
        state,
        parent: container,
      });
    } catch (error) {
      console.error('Failed to load source range:', error);
      if (view) {
        view.destroy();
        view = null;
      }
      container.textContent = 'Failed to load code';
    }
  }

  function detectLanguage(filePath: string) {
    if (filePath.endsWith('.py')) {
      return python();
    }
    if (filePath.endsWith('.js') || filePath.endsWith('.ts') || filePath.endsWith('.jsx') || filePath.endsWith('.tsx')) {
      return javascript();
    }
    return [];
  }

  return {
    loadSourceRange,
    get currentRange() {
      return currentRange;
    },
    destroy() {
      if (view) {
        view.destroy();
        view = null;
      }
    },
  };
}
