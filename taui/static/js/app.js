import { RpcClient } from "./rpc.js";
import { bindKeybindings } from "./keys.js";
import { createInitialState, reduce } from "./state.js";
import { renderTree } from "./tree.js";
import { syncTheme } from "./theme.js";

const stateHolder = { value: createInitialState() };
const treeElement = document.getElementById("spec-tree");
const connectionElement = document.getElementById("connection-status");
const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const rpc = new RpcClient(`${wsProtocol}://${window.location.host}/ws`);
let lastReloadToken = null;

function dispatch(action) {
  stateHolder.value = reduce(stateHolder.value, action);
  render();
}

function render() {
  const state = stateHolder.value;
  connectionElement.textContent = state.connected ? "Connected" : "Disconnected";

  renderTree({
    state,
    treeElement,
    onSelect: (nodeId) => dispatch({ type: "SELECT_NODE", nodeId }),
    onEditInput: (value) => dispatch({ type: "SET_EDIT_TEXT", value }),
    onEditSubmit: () => commitEdit(),
  });
}

async function loadTree() {
  const tree = await rpc.request("spec/getTree", {});
  dispatch({ type: "LOAD_TREE", nodes: tree.nodes || [] });
}

async function commitEdit() {
  const state = stateHolder.value;
  if (!state.editing || state.selectedNodeId === null) {
    return;
  }

  const selected = state.nodes[state.selectedNodeId];
  const nextTitle = state.editText.trim();
  dispatch({ type: "STOP_EDITING" });
  if (!nextTitle || nextTitle === selected.title) {
    return;
  }

  await rpc.request("spec/updateNode", {
    spec_ref: selected.spec_ref,
    patch: { title: nextTitle },
  });
  await loadTree();
}

async function bootstrap() {
  syncTheme();
  render();
  startHotReloadPolling();

  try {
    await rpc.connect();
    dispatch({ type: "SET_CONNECTED", value: true });
    await rpc.request("initialize", { workspace: window.location.pathname });
    await loadTree();
  } catch (error) {
    connectionElement.textContent = String(error);
    return;
  }

  rpc.onNotification(async (method) => {
    if (method === "spec/nodeChanged" || method === "spec/treeChanged") {
      await loadTree();
    }
  });

  bindKeybindings(window, {
    selectNext: () => dispatch({ type: "SELECT_NEXT" }),
    selectPrev: () => dispatch({ type: "SELECT_PREV" }),
    arrowLeft: () => dispatch({ type: "EXPAND_OR_PARENT" }),
    arrowRight: () => dispatch({ type: "COLLAPSE_OR_CHILD" }),
    startEditing: () => dispatch({ type: "START_EDITING" }),
    stopEditing: () => commitEdit(),
    enter: () => {
      if (stateHolder.value.editing) {
        commitEdit();
      } else {
        dispatch({ type: "START_EDITING" });
      }
    },
    toggleCollapse: () => dispatch({ type: "TOGGLE_COLLAPSE" }),
    cycleStatus: () => dispatch({ type: "CYCLE_STATUS" }),
  });
}

bootstrap();

function startHotReloadPolling() {
  const poll = async () => {
    try {
      const response = await fetch(`/__reload_token?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (typeof payload.token !== "number") {
        return;
      }
      if (lastReloadToken === null) {
        lastReloadToken = payload.token;
        return;
      }
      if (payload.token !== lastReloadToken) {
        window.location.reload();
      }
    } catch {
      // best-effort polling only
    }
  };

  poll();
  window.setInterval(poll, 800);
}
