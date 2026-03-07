import { State, visibleNodes, SpecNode } from './state';

export function renderTree({
  state,
  treeElement,
  onSelect,
  onEditInput,
  onEditSubmit,
  onToggleFold,
}: {
  state: State;
  treeElement: HTMLElement;
  onSelect: (nodeId: number) => void;
  onEditInput: (value: string) => void;
  onEditSubmit: () => void;
  onToggleFold: (nodeId: number) => void;
}) {
  const flat = visibleNodes(state);
  const baseDepth = flat.length > 0 ? Math.min(...flat.map((node) => node.depth)) : 1;
  treeElement.replaceChildren();

  for (const node of flat) {
    const displayDepth = Math.max(0, node.depth - baseDepth);
    const row = document.createElement('div');
    row.className = 'spec-row';
    if (node.id === state.selectedNodeId) {
      row.classList.add('selected');
    }
    row.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains('chevron')) {
        return;
      }
      onSelect(node.id);
    });

    const indentDepth = Math.max(0, displayDepth - 1);
    for (let i = 0; i < indentDepth; i += 1) {
      const indent = document.createElement('span');
      indent.className = 'indent';
      row.append(indent);
    }

    if (node.children.length > 0) {
      const chevron = document.createElement('span');
      chevron.className = `chevron ${node.collapsed ? 'collapsed' : 'expanded'}`;
      chevron.textContent = node.collapsed ? '▶' : '▼';
      chevron.addEventListener('click', (e) => {
        e.stopPropagation();
        onToggleFold(node.id);
      });
      row.append(chevron);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'chevron-spacer';
      row.append(spacer);
    }

    if (state.editing && node.id === state.selectedNodeId) {
      const input = document.createElement('input');
      input.className = `title-input depth-${Math.min(displayDepth, 3)}`;
      input.value = state.editText;
      input.autofocus = true;
      input.addEventListener('input', (event) => onEditInput((event.target as HTMLInputElement).value));
      input.addEventListener('blur', () => onEditSubmit());
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          onEditSubmit();
        }
      });
      row.append(input);
    } else {
      const textWrap = document.createElement('div');
      textWrap.className = 'title-wrap';

      const title = document.createElement('div');
      title.className = `title-text depth-${Math.min(displayDepth, 3)}`;
      title.textContent = node.title;
      textWrap.append(title);

      if (node.intent) {
        const intent = document.createElement('div');
        intent.className = 'intent-text';
        intent.textContent = node.intent;
        textWrap.append(intent);
      }

      row.append(textWrap);
    }

    const status = document.createElement('span');
    status.className = `status status-${node.status.replace(/-/g, '')}`;
    status.textContent = node.status;
    row.append(status);

    treeElement.append(row);
  }

  const activeInput = treeElement.querySelector('.title-input');
  if (activeInput instanceof HTMLInputElement) {
    activeInput.focus();
    activeInput.setSelectionRange(activeInput.value.length, activeInput.value.length);
  }
}
