import './styles/main.css';
import { RpcClient } from './rpc';
import { bindKeybindings } from './keys';
import { createInitialState, reduce, SpecNode, visibleNodes } from './state';
import { renderTree, NodeCodeReferenceState, CodeReferencePreview } from './tree';
import { syncTheme } from './theme';
import { createPerNodeEditorManager, PerNodeEditorManager } from './editors';

const FOLD_STATE_KEY = 'taui-fold-state';
const SELECTION_KEY = 'taui-selection';

interface CachedCodeReferenceState extends NodeCodeReferenceState {
  loaded: boolean;
}

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
  nodes.forEach((node) => {
    if (node.children.length > 0) {
      state[node.spec_ref] = node.collapsed;
    }
  });
  localStorage.setItem(FOLD_STATE_KEY, JSON.stringify(state));
}

function loadSelection(): string | null {
  try {
    return localStorage.getItem(SELECTION_KEY);
  } catch {
    return null;
  }
}

function saveSelection(specRef: string | null) {
  if (specRef) {
    localStorage.setItem(SELECTION_KEY, specRef);
  } else {
    localStorage.removeItem(SELECTION_KEY);
  }
}

const stateHolder = { value: createInitialState() };
const treeElement = document.getElementById('spec-tree');
const connectionPill = document.getElementById('connection-pill');

if (!treeElement) {
  throw new Error('Missing #spec-tree container');
}
const treeRoot = treeElement;

const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const rpc = new RpcClient(`${wsProtocol}://${window.location.host}/ws`);

let editorManager: PerNodeEditorManager | null = null;
let pendingFoldNodeId: number | null = null;
let renderInFlight = false;
let renderQueued = false;
let mountedEditors = new Set<string>();
const editorContainers = new Map<string, HTMLElement>();
const codeReferenceCache = new Map<string, CachedCodeReferenceState>();

function dispatch(action: any) {
  stateHolder.value = reduce(stateHolder.value, action);
  void scheduleRender();
}

function getEditorContainer(specRef: string): HTMLElement | null {
  return editorContainers.get(specRef) ?? null;
}

function registerEditorContainer(specRef: string, container: HTMLElement): void {
  container.dataset.specRef = specRef;
  editorContainers.set(specRef, container);
}

function getEditorState(specRef: string) {
  return editorManager?.getState(specRef);
}

function getCodeReferenceState(specRef: string): NodeCodeReferenceState | undefined {
  const cached = codeReferenceCache.get(specRef);
  if (!cached) {
    return undefined;
  }
  return {
    loading: cached.loading,
    error: cached.error,
    refs: cached.refs,
  };
}

async function render() {
  const state = stateHolder.value;

  renderTree({
    state,
    treeElement: treeRoot,
    callbacks: {
      onSelect: handleSelectNode,
      onToggleFold: handleToggleFold,
      getEditorContainer,
      registerEditorContainer,
      getEditorState,
      getCodeReferenceState,
    },
  });

  saveFoldState(state.nodes);

  const visible = visibleNodes(state);
  const visibleSpecRefs = new Set(visible.map((node) => node.spec_ref));

  for (const node of visible) {
    if (!mountedEditors.has(node.spec_ref)) {
      const container = getEditorContainer(node.spec_ref);
      if (container && editorManager) {
        await editorManager.mount(node.spec_ref, container);
        mountedEditors.add(node.spec_ref);
      }
    }
  }

  for (const specRef of Array.from(mountedEditors)) {
    if (!visibleSpecRefs.has(specRef)) {
      editorManager?.unmount(specRef);
      mountedEditors.delete(specRef);
    }
  }

  for (const node of visible) {
    void ensureCodeReferencesLoaded(node.spec_ref);
  }

  if (pendingFoldNodeId !== null) {
    const allSaved = !editorManager?.hasUnsavedChanges();
    if (allSaved) {
      const nodeId = pendingFoldNodeId;
      pendingFoldNodeId = null;
      dispatch({ type: 'TOGGLE_FOLD', nodeId });
    }
  }

  if (connectionPill) {
    connectionPill.textContent = state.connected ? 'Connected' : 'Disconnected';
    connectionPill.classList.toggle('connected', state.connected);
    connectionPill.classList.toggle('disconnected', !state.connected);
  }

  if (state.selectedNodeId !== null) {
    const selectedNode = state.nodes[state.selectedNodeId];
    saveSelection(selectedNode.spec_ref);
  } else {
    saveSelection(null);
  }
}

async function scheduleRender() {
  if (renderInFlight) {
    renderQueued = true;
    return;
  }

  renderInFlight = true;
  try {
    await render();
  } finally {
    renderInFlight = false;
    if (renderQueued) {
      renderQueued = false;
      await scheduleRender();
    }
  }
}

async function ensureCodeReferencesLoaded(specRef: string, force: boolean = false) {
  const cached = codeReferenceCache.get(specRef);
  if (!force && cached?.loaded) {
    return;
  }
  if (cached?.loading) {
    return;
  }

  codeReferenceCache.set(specRef, {
    loaded: true,
    loading: true,
    error: null,
    refs: cached?.refs ?? [],
  });
  void scheduleRender();

  try {
    const result = await rpc.request('spec/getNodeCodeRefs', {
      spec_ref: specRef,
      max_lines: 240,
    });
    const refs = Array.isArray(result?.refs)
      ? (result.refs as CodeReferencePreview[])
      : [];

    codeReferenceCache.set(specRef, {
      loaded: true,
      loading: false,
      error: null,
      refs,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Failed to load code references';
    codeReferenceCache.set(specRef, {
      loaded: true,
      loading: false,
      error: message,
      refs: [],
    });
  }

  void scheduleRender();
}

async function handleSelectNode(nodeId: number) {
  if (editorManager?.hasUnsavedChanges()) {
    await editorManager.saveAll();
  }

  dispatch({ type: 'SELECT_NODE', nodeId });
}

async function handleToggleFold(nodeId: number) {
  const state = stateHolder.value;
  const node = state.nodes[nodeId];

  if (!node.collapsed && editorManager?.hasUnsavedChanges()) {
    await editorManager.saveAll();
    if (editorManager.hasUnsavedChanges()) {
      pendingFoldNodeId = nodeId;
      return;
    }
  }

  dispatch({ type: 'TOGGLE_FOLD', nodeId });
}

async function loadTree() {
  const state = stateHolder.value;
  const previousSelectedSpecRef =
    state.selectedNodeId !== null
      ? state.nodes[state.selectedNodeId]?.spec_ref
      : loadSelection();

  const unsavedContent = editorManager?.getUnsavedContent() ?? new Map();

  const tree = await rpc.request('spec/getTree', {});
  const foldState = loadFoldState();
  dispatch({
    type: 'LOAD_TREE',
    nodes: tree.nodes || [],
    foldState,
    preserveSelection: true,
    previousSelectedSpecRef,
  });

  const currentState = stateHolder.value;
  const validRefs = new Set(currentState.nodes.map((node) => node.spec_ref));

  for (const specRef of Array.from(editorContainers.keys())) {
    if (!validRefs.has(specRef)) {
      editorContainers.delete(specRef);
    }
  }
  for (const specRef of Array.from(codeReferenceCache.keys())) {
    if (!validRefs.has(specRef)) {
      codeReferenceCache.delete(specRef);
    }
  }

  if (unsavedContent.size > 0) {
    const specRefMap = new Map<string, string>();

    for (const node of currentState.nodes) {
      for (const [oldSpecRef] of unsavedContent) {
        if (oldSpecRef === node.spec_ref) {
          specRefMap.set(oldSpecRef, node.spec_ref);
        }
      }
    }

    const contentToRestore = new Map<string, string>();
    for (const [oldSpecRef, content] of unsavedContent) {
      const newSpecRef = specRefMap.get(oldSpecRef);
      if (newSpecRef) {
        contentToRestore.set(newSpecRef, content);
      }
    }

    if (contentToRestore.size > 0) {
      editorManager?.restoreContent(contentToRestore);
    }
  }
}

async function handleTreeChanged(params: any) {
  const oldSpecRef =
    typeof params?.old_spec_ref === 'string'
      ? params.old_spec_ref
      : typeof params?.previous_spec_ref === 'string'
        ? params.previous_spec_ref
        : null;

  const newSpecRef =
    typeof params?.new_spec_ref === 'string'
      ? params.new_spec_ref
      : typeof params?.spec_ref === 'string'
        ? params.spec_ref
        : null;

  if (oldSpecRef && newSpecRef) {
    editorManager?.remapSpecRef(oldSpecRef, newSpecRef);

    if (mountedEditors.has(oldSpecRef)) {
      mountedEditors.delete(oldSpecRef);
      mountedEditors.add(newSpecRef);
    }

    const container = editorContainers.get(oldSpecRef);
    if (container) {
      editorContainers.delete(oldSpecRef);
      container.dataset.specRef = newSpecRef;
      editorContainers.set(newSpecRef, container);
    }

    codeReferenceCache.delete(oldSpecRef);
    codeReferenceCache.delete(newSpecRef);
  }

  await loadTree();
}

async function bootstrap() {
  syncTheme();

  editorManager = createPerNodeEditorManager(rpc);

  await scheduleRender();

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
    if (method === 'spec/nodeChanged') {
      const specRef =
        typeof params?.node?.spec_ref === 'string' ? params.node.spec_ref : null;
      if (specRef) {
        codeReferenceCache.delete(specRef);
      }
      await loadTree();
      return;
    }

    if (method === 'spec/treeChanged') {
      await handleTreeChanged(params);
    }
  });

  bindKeybindings(window, {
    selectNext: () => handleSelectNext(),
    selectPrev: () => handleSelectPrev(),
    arrowLeft: () => dispatch({ type: 'EXPAND_OR_PARENT' }),
    arrowRight: () => dispatch({ type: 'COLLAPSE_OR_CHILD' }),
    toggleCollapse: () => dispatch({ type: 'TOGGLE_COLLAPSE' }),
    cycleStatus: () => dispatch({ type: 'CYCLE_STATUS' }),
  });
}

async function handleSelectNext() {
  if (editorManager?.hasUnsavedChanges()) {
    await editorManager.saveAll();
  }
  dispatch({ type: 'SELECT_NEXT' });
}

async function handleSelectPrev() {
  if (editorManager?.hasUnsavedChanges()) {
    await editorManager.saveAll();
  }
  dispatch({ type: 'SELECT_PREV' });
}

bootstrap();
