const STATUS_FLOW = ["draft", "ready", "in-progress", "done", "blocked"];

export function createInitialState() {
  return {
    nodes: [],
    selectedNodeId: null,
    editing: false,
    editText: "",
    connected: false,
  };
}

export function buildTree(nodesFromServer) {
  const nodes = nodesFromServer.map((node, idx) => ({
    id: idx,
    spec_ref: node.spec_ref,
    title: node.title,
    intent: typeof node.intent === "string" ? node.intent : "",
    depth: Number(node.depth || 1),
    status: normalizeStatus(node.status),
    collapsed: false,
    parentId: null,
    children: [],
  }));

  const stack = [];
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

export function visibleNodes(state) {
  const out = [];
  const roots = state.nodes.filter((node) => node.parentId === null).map((node) => node.id);

  function visit(nodeId) {
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

export function reduce(state, action) {
  if (action.type === "SET_CONNECTED") {
    return { ...state, connected: action.value };
  }

  if (action.type === "LOAD_TREE") {
    const nodes = buildTree(action.nodes);
    const selectedNodeId = nodes.length > 0 ? nodes[0].id : null;
    return {
      ...state,
      nodes,
      selectedNodeId,
      editing: false,
      editText: selectedNodeId === null ? "" : nodes[selectedNodeId].title,
    };
  }

  if (state.selectedNodeId === null || state.nodes.length === 0) {
    return state;
  }

  const node = state.nodes[state.selectedNodeId];

  if (action.type === "SELECT_NODE") {
    const selected = state.nodes[action.nodeId];
    if (!selected) {
      return state;
    }
    return {
      ...state,
      selectedNodeId: action.nodeId,
      editing: false,
      editText: selected.title,
    };
  }

  if (action.type === "SELECT_NEXT" || action.type === "SELECT_PREV") {
    const flat = visibleNodes(state);
    const idx = flat.findIndex((item) => item.id === state.selectedNodeId);
    if (idx < 0) {
      return state;
    }
    const nextIdx = action.type === "SELECT_NEXT" ? idx + 1 : idx - 1;
    if (nextIdx < 0 || nextIdx >= flat.length) {
      return state;
    }
    const selected = flat[nextIdx];
    return {
      ...state,
      selectedNodeId: selected.id,
      editing: false,
      editText: selected.title,
    };
  }

  if (action.type === "TOGGLE_COLLAPSE") {
    const nodes = state.nodes.slice();
    nodes[state.selectedNodeId] = { ...node, collapsed: !node.collapsed };
    return { ...state, nodes };
  }

  if (action.type === "CYCLE_STATUS") {
    const nodes = state.nodes.slice();
    const nextStatus = STATUS_FLOW[(STATUS_FLOW.indexOf(node.status) + 1) % STATUS_FLOW.length];
    nodes[state.selectedNodeId] = { ...node, status: nextStatus };
    return { ...state, nodes };
  }

  if (action.type === "START_EDITING") {
    return { ...state, editing: true, editText: node.title };
  }

  if (action.type === "SET_EDIT_TEXT") {
    if (!state.editing) {
      return state;
    }
    return { ...state, editText: action.value };
  }

  if (action.type === "STOP_EDITING") {
    return { ...state, editing: false };
  }

  if (action.type === "EXPAND_OR_PARENT") {
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
      };
    }
    return state;
  }

  if (action.type === "COLLAPSE_OR_CHILD") {
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
      };
    }
    return state;
  }

  return state;
}

function normalizeStatus(status) {
  if (typeof status !== "string") {
    return "draft";
  }
  const normalized = status.trim().toLowerCase().replace(/[_\s]+/g, "-");
  return STATUS_FLOW.includes(normalized) ? normalized : "draft";
}
