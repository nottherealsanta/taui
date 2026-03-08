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
  connected: boolean;
  // Note: Per-node editor state is managed by PerNodeEditorManager in editors.ts
}

export function createInitialState(): State {
  return {
    nodes: [],
    selectedNodeId: null,
    connected: false,
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

  if (action.type === 'LOAD_TREE') {
    const nodes = buildTree(action.nodes, action.foldState || {});
    // Preserve selection by spec_ref if possible
    let selectedNodeId: number | null = null;
    if (action.preserveSelection && action.previousSelectedSpecRef) {
      const found = nodes.find(n => n.spec_ref === action.previousSelectedSpecRef);
      if (found) {
        selectedNodeId = found.id;
      }
    }
    if (selectedNodeId === null && nodes.length > 0) {
      selectedNodeId = nodes[0].id;
    }
    return {
      ...state,
      nodes,
      selectedNodeId,
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
    return {
      ...state,
      selectedNodeId: flat[nextIdx].id,
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

  if (action.type === 'EXPAND_OR_PARENT') {
    if (node.children.length > 0 && node.collapsed) {
      const nodes = state.nodes.slice();
      nodes[state.selectedNodeId] = { ...node, collapsed: false };
      return { ...state, nodes };
    }
    if (node.parentId !== null) {
      return {
        ...state,
        selectedNodeId: node.parentId,
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
      return {
        ...state,
        selectedNodeId: node.children[0],
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
