const STATUS_FLOW = ['draft', 'ready', 'in-progress', 'done', 'blocked'];

export interface SpecNode {
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

export interface State {
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

export function createInitialState(): State {
  return {
    nodes: [],
    selectedNodeId: null,
    editing: false,
    editText: '',
    connected: false,
    activeTab: 'code',
    codeExpanded: false,
    nodeContent: '',
    nodeDirty: false,
    codeContent: '',
    codeRange: null,
    terminalOutput: [],
    runStatus: 'idle',
  };
}

export function buildTree(nodesFromServer: any[], foldState: Record<string, boolean> = {}): SpecNode[] {
  const nodes: SpecNode[] = nodesFromServer.map((node, idx) => ({
    id: idx,
    spec_ref: node.spec_ref,
    title: node.title,
    intent: typeof node.intent === 'string' ? node.intent : '',
    depth: Number(node.depth || 1),
    status: normalizeStatus(node.status),
    collapsed: foldState[node.spec_ref] ?? false,
    parentId: null,
    children: [],
  }));

  const stack: SpecNode[] = [];
  for (const node of nodes) {
    while (stack.length > 0 && stack[stack.length - 1].depth >= node.depth) {
      stack.pop();
    }
    node.parentId = stack.length > 0 ? stack[stack.length - 1].id : null;
    if (node.parentId !== null) {
      nodes[node.parentId].children.push(node.id);
    }
    stack.push(node);
  }
  return nodes;
}

export function visibleNodes(state: State): SpecNode[] {
  const out: SpecNode[] = [];
  const roots = state.nodes.filter((node) => node.parentId === null).map((node) => node.id);

  function visit(nodeId: number) {
    const node = state.nodes[nodeId];
    out.push(node);
    if (node.collapsed) {
      return;
    }
    for (const childId of node.children) {
      visit(childId);
    }
  }

  for (const rootId of roots) {
    visit(rootId);
  }
  return out;
}

export function reduce(state: State, action: any): State {
  if (action.type === 'SET_CONNECTED') {
    return { ...state, connected: action.value };
  }

  if (action.type === 'SET_ACTIVE_TAB') {
    return { ...state, activeTab: action.tab };
  }

  if (action.type === 'TOGGLE_CODE_EXPANDED') {
    return { ...state, codeExpanded: !state.codeExpanded };
  }

  if (action.type === 'SET_RUN_STATUS') {
    return { ...state, runStatus: action.status };
  }

  if (action.type === 'APPEND_TERMINAL_OUTPUT') {
    return { ...state, terminalOutput: [...state.terminalOutput, action.line] };
  }

  if (action.type === 'LOAD_TREE') {
    const nodes = buildTree(action.nodes, action.foldState || {});
    const selectedNodeId = nodes.length > 0 ? nodes[0].id : null;
    return {
      ...state,
      nodes,
      selectedNodeId,
      editing: false,
      editText: selectedNodeId === null ? '' : nodes[selectedNodeId].title,
    };
  }

  if (state.selectedNodeId === null || state.nodes.length === 0) {
    return state;
  }

  const node = state.nodes[state.selectedNodeId];

  if (action.type === 'SELECT_NODE') {
    const selected = state.nodes[action.nodeId];
    if (!selected) {
      return state;
    }
    return {
      ...state,
      selectedNodeId: action.nodeId,
      editing: false,
      editText: selected.title,
      nodeDirty: false,
    };
  }

  if (action.type === 'SELECT_NEXT' || action.type === 'SELECT_PREV') {
    const flat = visibleNodes(state);
    const idx = flat.findIndex((item) => item.id === state.selectedNodeId);
    if (idx < 0) {
      return state;
    }
    const nextIdx = action.type === 'SELECT_NEXT' ? idx + 1 : idx - 1;
    if (nextIdx < 0 || nextIdx >= flat.length) {
      return state;
    }
    const selected = flat[nextIdx];
    return {
      ...state,
      selectedNodeId: selected.id,
      editing: false,
      editText: selected.title,
      nodeDirty: false,
    };
  }

  if (action.type === 'TOGGLE_COLLAPSE') {
    const nodes = state.nodes.slice();
    nodes[state.selectedNodeId] = { ...node, collapsed: !node.collapsed };
    return { ...state, nodes };
  }

  if (action.type === 'TOGGLE_FOLD') {
    const targetNode = state.nodes[action.nodeId];
    if (!targetNode || targetNode.children.length === 0) {
      return state;
    }
    const nodes = state.nodes.slice();
    nodes[action.nodeId] = { ...targetNode, collapsed: !targetNode.collapsed };
    return { ...state, nodes };
  }

  if (action.type === 'CYCLE_STATUS') {
    const nodes = state.nodes.slice();
    const nextStatus = STATUS_FLOW[(STATUS_FLOW.indexOf(node.status) + 1) % STATUS_FLOW.length];
    nodes[state.selectedNodeId] = { ...node, status: nextStatus };
    return { ...state, nodes };
  }

  if (action.type === 'START_EDITING') {
    return { ...state, editing: true, editText: node.title };
  }

  if (action.type === 'SET_EDIT_TEXT') {
    if (!state.editing) {
      return state;
    }
    return { ...state, editText: action.value };
  }

  if (action.type === 'STOP_EDITING') {
    return { ...state, editing: false };
  }

  if (action.type === 'SET_NODE_DIRTY') {
    return { ...state, nodeDirty: action.value };
  }

  if (action.type === 'EXPAND_OR_PARENT') {
    if (node.children.length > 0 && node.collapsed) {
      const nodes = state.nodes.slice();
      nodes[state.selectedNodeId] = { ...node, collapsed: false };
      return { ...state, nodes };
    }
    if (node.parentId !== null) {
      const parent = state.nodes[node.parentId];
      return {
        ...state,
        selectedNodeId: parent.id,
        editing: false,
        editText: parent.title,
        nodeDirty: false,
      };
    }
    return state;
  }

  if (action.type === 'COLLAPSE_OR_CHILD') {
    if (node.children.length > 0 && !node.collapsed) {
      const nodes = state.nodes.slice();
      nodes[state.selectedNodeId] = { ...node, collapsed: true };
      return { ...state, nodes };
    }
    if (node.children.length > 0) {
      const child = state.nodes[node.children[0]];
      return {
        ...state,
        selectedNodeId: child.id,
        editing: false,
        editText: child.title,
        nodeDirty: false,
      };
    }
    return state;
  }

  return state;
}

function normalizeStatus(status: any): string {
  if (typeof status !== 'string') {
    return 'draft';
  }
  const normalized = status.trim().toLowerCase().replace(/[_\s]+/g, '-');
  return STATUS_FLOW.includes(normalized) ? normalized : 'draft';
}
