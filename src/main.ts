import './styles/main.css';
import { RpcClient } from './rpc';
import { bindKeybindings } from './keys';
import { createInitialState, reduce, visibleNodes } from './state';
import { renderTree } from './tree';
import { syncTheme } from './theme';
import { createEditor } from './editor';
import { createCodePreview } from './code-preview';
import { createTerminal } from './terminal';

interface SpecNode {
  id: number;
  spec_ref: string;
  title: string;
  intent: string;
  depth: number;
  status: string;
  collapsed: boolean;
  parentId: number | null;
  children: number[];
}

interface State {
  nodes: SpecNode[];
  selectedNodeId: number | null;
  editing: boolean;
  editText: string;
  connected: boolean;
  activeTab: 'code' | 'terminal';
  codeExpanded: boolean;
  nodeContent: string;
  nodeDirty: boolean;
  codeContent: string;
  codeRange: { file_path: string; line_start: number; line_end: number } | null;
  terminalOutput: string[];
  runStatus: 'idle' | 'running' | 'stopped';
}

const FOLD_STATE_KEY = 'taui-fold-state';

function loadFoldState(): Record<string, boolean> {
  try {
    const stored = localStorage.getItem(FOLD_STATE_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch {
    return {};
  }
}

function saveFoldState(nodes: SpecNode[]) {
  const state: Record<string, boolean> = {};
  nodes.forEach(node => {
    if (node.children.length > 0) {
      state[node.spec_ref] = node.collapsed;
    }
  });
  localStorage.setItem(FOLD_STATE_KEY, JSON.stringify(state));
}

const stateHolder = { value: createInitialState() };
const treeElement = document.getElementById('spec-tree')!;
const drawerElement = document.getElementById('bottom-drawer')!;
const codeTabElement = document.getElementById('code-tab')!;
const terminalTabElement = document.getElementById('terminal-tab')!;
const codeContentElement = document.getElementById('code-content')!;
const terminalContentElement = document.getElementById('terminal-content')!;

const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const rpc = new RpcClient(`${wsProtocol}://${window.location.host}/ws`);

let editorInstance: ReturnType<typeof createEditor> | null = null;
let terminalInstance: ReturnType<typeof createTerminal> | null = null;
let codePreviewInstance: ReturnType<typeof createCodePreview> | null = null;

function dispatch(action: any) {
  stateHolder.value = reduce(stateHolder.value, action);
  render();
}

async function render() {
  const state = stateHolder.value as State;

  renderTree({
    state,
    treeElement,
    onSelect: (nodeId: number) => dispatch({ type: 'SELECT_NODE', nodeId }),
    onEditInput: (value: string) => dispatch({ type: 'SET_EDIT_TEXT', value }),
    onEditSubmit: () => commitEdit(),
    onToggleFold: (nodeId: number) => dispatch({ type: 'TOGGLE_FOLD', nodeId }),
  });

  saveFoldState(state.nodes);

  if (state.selectedNodeId !== null) {
    const selectedNode = state.nodes[state.selectedNodeId];
    if (editorInstance) {
      await editorInstance.loadContent(selectedNode.spec_ref);
    }
    if (codePreviewInstance) {
      await codePreviewInstance.loadSourceRange(selectedNode.spec_ref, state.codeExpanded);
    }
  }

  if (state.activeTab === 'code') {
    codeTabElement.classList.add('active');
    terminalTabElement.classList.remove('active');
    codeContentElement.style.display = 'block';
    terminalContentElement.style.display = 'none';
  } else {
    codeTabElement.classList.remove('active');
    terminalTabElement.classList.add('active');
    codeContentElement.style.display = 'none';
    terminalContentElement.style.display = 'block';
  }
}

async function loadTree() {
  const tree = await rpc.request('spec/getTree', {});
  const foldState = loadFoldState();
  dispatch({ type: 'LOAD_TREE', nodes: tree.nodes || [], foldState });
}

async function commitEdit() {
  const state = stateHolder.value as State;
  if (!state.editing || state.selectedNodeId === null) {
    return;
  }

  const selected = state.nodes[state.selectedNodeId];
  const nextTitle = state.editText.trim();
  dispatch({ type: 'STOP_EDITING' });
  if (!nextTitle || nextTitle === selected.title) {
    return;
  }

  await rpc.request('spec/updateNode', {
    spec_ref: selected.spec_ref,
    patch: { title: nextTitle },
  });
  await loadTree();
}

async function bootstrap() {
  syncTheme();
  
  editorInstance = createEditor(document.getElementById('editor-container')!);
  terminalInstance = createTerminal(document.getElementById('terminal-container')!, rpc);
  codePreviewInstance = createCodePreview(document.getElementById('code-container')!);
  
  render();

  try {
    await rpc.connect();
    dispatch({ type: 'SET_CONNECTED', value: true });
    await rpc.request('initialize', { workspace: window.location.pathname });
    await loadTree();
  } catch (error) {
    console.error(error);
    return;
  }

  rpc.onNotification(async (method: string, params: any) => {
    if (method === 'spec/nodeChanged' || method === 'spec/treeChanged') {
      await loadTree();
    }
    if (method === 'run/output' && terminalInstance) {
      terminalInstance.appendOutput(params.line);
    }
    if (method === 'run/completed') {
      dispatch({ type: 'SET_RUN_STATUS', status: 'idle' });
    }
  });

  bindKeybindings(window, {
    selectNext: () => dispatch({ type: 'SELECT_NEXT' }),
    selectPrev: () => dispatch({ type: 'SELECT_PREV' }),
    arrowLeft: () => dispatch({ type: 'EXPAND_OR_PARENT' }),
    arrowRight: () => dispatch({ type: 'COLLAPSE_OR_CHILD' }),
    startEditing: () => dispatch({ type: 'START_EDITING' }),
    stopEditing: () => commitEdit(),
    enter: () => {
      const state = stateHolder.value as State;
      if (state.editing) {
        commitEdit();
      } else {
        dispatch({ type: 'START_EDITING' });
      }
    },
    toggleCollapse: () => dispatch({ type: 'TOGGLE_COLLAPSE' }),
    cycleStatus: () => dispatch({ type: 'CYCLE_STATUS' }),
  });

  codeTabElement.addEventListener('click', () => {
    dispatch({ type: 'SET_ACTIVE_TAB', tab: 'code' });
  });

  terminalTabElement.addEventListener('click', () => {
    dispatch({ type: 'SET_ACTIVE_TAB', tab: 'terminal' });
  });

  const expandCodeBtn = document.getElementById('expand-code-btn');
  if (expandCodeBtn) {
    expandCodeBtn.addEventListener('click', async () => {
      const state = stateHolder.value as State;
      dispatch({ type: 'TOGGLE_CODE_EXPANDED' });
      if (state.selectedNodeId !== null && codePreviewInstance) {
        const selectedNode = state.nodes[state.selectedNodeId];
        await codePreviewInstance.loadSourceRange(selectedNode.spec_ref, !state.codeExpanded);
      }
    });
  }
}

bootstrap();
