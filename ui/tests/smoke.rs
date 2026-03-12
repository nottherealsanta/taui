use taui_ui::app::state::{AppState, BackendNode};

#[test]
fn demo_state_boots_with_selection_and_spec_ref() {
    let state = AppState::demo();

    assert!(state.selected_node.is_some());
    assert!(state.selected_spec_ref().is_some());
    assert!(!state.flattened_nodes().is_empty());
}

// ---------------------------------------------------------------------------
// Virtualization correctness: flattened_tree_nodes must exclude the primary
// root so the uniform_list row count matches the non-root visible rows.
// ---------------------------------------------------------------------------

#[test]
fn flattened_tree_nodes_count_excludes_root() {
    let state = AppState::demo();
    let all = state.flattened_nodes();
    let tree = state.flattened_tree_nodes();
    // flattened_tree_nodes must be strictly smaller (root is excluded).
    assert!(tree.len() < all.len());
}

#[test]
fn flattened_tree_nodes_count_matches_visible_row_budget() {
    // After hydrate the row count must equal the sum of visible (non-collapsed)
    // non-root nodes — i.e. the uniform_list item_count is always tight.
    let mut state = AppState::demo();
    state.hydrate_from_backend(vec![
        BackendNode {
            spec_ref: "a".into(),
            depth: 0,
            markdown: "Root".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
        BackendNode {
            spec_ref: "b".into(),
            depth: 1,
            markdown: "Child 1".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
        BackendNode {
            spec_ref: "c".into(),
            depth: 1,
            markdown: "Child 2".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
        BackendNode {
            spec_ref: "d".into(),
            depth: 2,
            markdown: "Grandchild".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
    ]);
    let tree = state.flattened_tree_nodes();
    // Non-root visible: Child 1, Child 2, Grandchild = 3
    assert_eq!(tree.len(), 3);
}

#[test]
fn collapsed_node_reduces_uniform_list_row_count() {
    let mut state = AppState::demo();
    state.hydrate_from_backend(vec![
        BackendNode {
            spec_ref: "a".into(),
            depth: 0,
            markdown: "Root".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
        BackendNode {
            spec_ref: "b".into(),
            depth: 1,
            markdown: "Child".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
        BackendNode {
            spec_ref: "c".into(),
            depth: 2,
            markdown: "Grandchild".into(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        },
    ]);
    let before = state.flattened_tree_nodes().len(); // 2: Child + Grandchild

    // Collapse the child
    let child_id = state.spec_ref_index["b"];
    state.set_selected(child_id);
    state.toggle_collapse();

    let after = state.flattened_tree_nodes().len(); // 1: only Child (grandchild hidden)
    assert!(after < before, "collapse must reduce visible row count");
    assert_eq!(after, 1);
}

// ---------------------------------------------------------------------------
// Incremental flat-tree update: select_node path must not require full rebuild
// by verifying the selected field in flattened output is consistent.
// ---------------------------------------------------------------------------

#[test]
fn set_selected_reflects_in_flattened_nodes() {
    let mut state = AppState::demo();
    let root_id = state.primary_root_id().unwrap();
    let child_id = state.nodes[root_id].children[0];

    state.set_selected(child_id);
    let flat = state.flattened_tree_nodes();
    let selected_count = flat.iter().filter(|n| n.selected).count();
    // Exactly one node should be marked selected.
    assert_eq!(selected_count, 1);
    let selected_node = flat.iter().find(|n| n.selected).unwrap();
    assert_eq!(selected_node.id, child_id);
}

// ---------------------------------------------------------------------------
// Backend client: start_run guards empty spec_ref.
// ---------------------------------------------------------------------------

#[test]
fn start_run_rejects_empty_spec_ref() {
    use taui_ui::services::backend_client::BackendClient;
    let client = BackendClient::new("ws://127.0.0.1:9999/ws");
    assert!(client.start_run("").is_err());
    assert!(client.start_run("   ").is_err());
}
