use pretty_assertions::assert_eq;

use taui_ui::app::actions::{dispatch, UiAction};
use taui_ui::app::state::AppState;

fn first_line(markdown: &str) -> &str {
    markdown.lines().next().unwrap_or("")
}

#[test]
fn add_sibling_node_selects_new_node() {
    let mut state = AppState::demo();
    let before = state.flattened_nodes().len();

    let changed = dispatch(&mut state, UiAction::AddSiblingNode);

    assert!(changed);
    assert_eq!(state.flattened_nodes().len(), before + 1);
    let selected = state.selected_node.expect("selected node");
    assert_eq!(state.nodes[selected].markdown, "");
}

#[test]
fn tab_indent_makes_previous_sibling_parent() {
    let mut state = AppState::demo();

    let target = state
        .nodes
        .iter()
        .find(|node| first_line(&node.markdown) == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));

    let changed = dispatch(&mut state, UiAction::IndentNode);

    assert!(changed);
    let selected = state.selected_node.expect("selected node");
    let parent = state.nodes[selected].parent.expect("has new parent");
    assert_eq!(first_line(&state.nodes[parent].markdown), "Editable Nodes");
}

#[test]
fn shift_tab_outdents_node() {
    let mut state = AppState::demo();

    let target = state
        .nodes
        .iter()
        .find(|node| first_line(&node.markdown) == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));
    dispatch(&mut state, UiAction::IndentNode);

    let changed = dispatch(&mut state, UiAction::OutdentNode);

    assert!(changed);
    let selected = state.selected_node.expect("selected node");
    let parent = state.nodes[selected].parent.expect("has parent");
    assert_eq!(first_line(&state.nodes[parent].markdown), "Spec Tree Pane");
}

#[test]
fn toolbar_actions_maintain_behavioral_parity() {
    let mut state = AppState::demo();

    let initial_count = state.flattened_nodes().len();
    dispatch(&mut state, UiAction::AddSiblingNode);
    assert_eq!(state.flattened_nodes().len(), initial_count + 1);

    let target = state
        .nodes
        .iter()
        .find(|node| first_line(&node.markdown) == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));
    let parent_before = state.nodes[target].parent;
    dispatch(&mut state, UiAction::IndentNode);
    let parent_after = state.nodes[target].parent;
    assert_ne!(parent_before, parent_after);

    let parent_before = state.nodes[target].parent;
    dispatch(&mut state, UiAction::OutdentNode);
    let parent_after = state.nodes[target].parent;
    assert_ne!(parent_before, parent_after);
}

#[test]
fn indent_preserves_selection() {
    let mut state = AppState::demo();

    let target = state
        .nodes
        .iter()
        .find(|node| first_line(&node.markdown) == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));

    let selected_before = state.selected_node;
    dispatch(&mut state, UiAction::IndentNode);

    assert_eq!(state.selected_node, selected_before);
}

#[test]
fn keybinding_tab_indents_node() {
    let tab_action =
        taui_ui::app::keybindings::map_key_to_action(&gpui::Keystroke::parse("tab").unwrap());
    assert_eq!(tab_action, Some(UiAction::IndentNode));
}

#[test]
fn keybinding_shift_tab_outdents_node() {
    let shift_tab_action =
        taui_ui::app::keybindings::map_key_to_action(&gpui::Keystroke::parse("shift-tab").unwrap());
    assert_eq!(shift_tab_action, Some(UiAction::OutdentNode));
}

// ── Split node tests ──────────────────────────────────────────────────────────

#[test]
fn split_at_mid_creates_two_sibling_nodes() {
    let mut state = AppState::demo();
    // Select "Editable Nodes" which has a known prefix
    let target = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("node")
        .id;
    state.set_selected(target);

    let text = state.nodes[target].markdown.clone();
    // Split at byte 8 ("Editable")
    let split_offset = 8;
    let fst_expected = text[..split_offset].to_string();
    let snd_expected = text[split_offset..].trim_start_matches('\n').to_string();

    let new_id = state
        .split_selected_at(split_offset)
        .expect("split succeeds");

    // First half stays in original node (now previous sibling / parent)
    // The split node (new_id) is now selected.
    assert_eq!(state.selected_node, Some(new_id));

    // Check text content of both halves.
    // The original node's markdown should be the first half.
    let original_id = target;
    assert_eq!(state.nodes[original_id].markdown, fst_expected);
    assert_eq!(state.nodes[new_id].markdown, snd_expected);
}

#[test]
fn split_at_zero_inserts_empty_node_before() {
    let mut state = AppState::demo();
    let target = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("node")
        .id;
    let original_text = state.nodes[target].markdown.clone();
    state.set_selected(target);

    let new_id = state.split_selected_at(0).expect("split at zero");

    // Original node keeps its full text (snd = trimmed from offset 0 = full text).
    // Original node gets the first half = "" (empty).
    assert_eq!(state.nodes[target].markdown, "");
    assert_eq!(state.nodes[new_id].markdown, original_text);
    assert_eq!(state.selected_node, Some(new_id));
}

#[test]
fn split_increases_node_count() {
    let mut state = AppState::demo();
    let count_before = state.flattened_nodes().len();
    let target = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("node")
        .id;
    state.set_selected(target);
    state.split_selected_at(4).expect("split");
    assert_eq!(state.flattened_nodes().len(), count_before + 1);
}

#[test]
fn split_node_with_children_inserts_as_first_child() {
    let mut state = AppState::demo();
    // "Spec Tree Pane" has children ("Editable Nodes", "Tab Indent")
    let target = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("node")
        .id;
    state.set_selected(target);
    let child_count_before = state.nodes[target].children.len();

    state.split_selected_at(4).expect("split");

    // The new node should be the first child of the original node.
    let new_id = state.selected_node.expect("new node selected");
    assert_eq!(state.nodes[target].children[0], new_id);
    assert_eq!(state.nodes[target].children.len(), child_count_before + 1);
}

// ── Merge with previous tests ────────────────────────────────────────────────

#[test]
fn merge_with_previous_combines_text_at_join_seam() {
    let mut state = AppState::demo();
    // "Editable Nodes" appears after "Spec Tree Pane" in the flat list.
    let prev_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("prev node")
        .id;
    let target_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("target node")
        .id;

    let prev_text = state.nodes[prev_id].markdown.clone();
    let target_text = state.nodes[target_id].markdown.clone();
    let expected_join_offset = prev_text.len();

    state.set_selected(target_id);
    let result = state
        .merge_selected_into_previous()
        .expect("merge succeeds");

    assert_eq!(result.0, prev_id);
    assert_eq!(result.1, expected_join_offset);
    assert_eq!(
        state.nodes[prev_id].markdown,
        format!("{}{}", prev_text, target_text)
    );
    assert_eq!(state.selected_node, Some(prev_id));
}

#[test]
fn merge_with_previous_decreases_node_count() {
    let mut state = AppState::demo();
    let count_before = state.flattened_nodes().len();
    let target_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("target node")
        .id;
    state.set_selected(target_id);
    state.merge_selected_into_previous().expect("merge");
    assert_eq!(state.flattened_nodes().len(), count_before - 1);
}

#[test]
fn merge_with_previous_reparents_children() {
    let mut state = AppState::demo();
    // Add a child to "Editable Nodes" so we can test reparenting.
    let target_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("target node")
        .id;
    let prev_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("prev node")
        .id;
    let child_id = state.create_node(
        "local/child".to_string(),
        "child".to_string(),
        Some(target_id),
    );
    state.nodes[target_id].children.push(child_id);

    state.set_selected(target_id);
    state.merge_selected_into_previous().expect("merge");

    // Child should now be parented to prev_id.
    assert_eq!(state.nodes[child_id].parent, Some(prev_id));
    assert!(state.nodes[prev_id].children.contains(&child_id));
}

#[test]
fn merge_with_previous_at_first_node_returns_none() {
    let mut state = AppState::demo();
    // "Spec Tree Pane" is first in the flat tree (after root).
    let first_id = state.flattened_nodes()[0].id;
    state.set_selected(first_id);
    // The first node's previous in flattened_nodes is the primary root, which
    // merge refuses to touch — should return None.
    // (If there's no previous at all, also returns None.)
    let result = state.merge_selected_into_previous();
    assert!(
        result.is_none(),
        "should not merge at the very first editable node"
    );
}

// ── Merge with next tests ────────────────────────────────────────────────────

#[test]
fn merge_next_into_selected_combines_text() {
    let mut state = AppState::demo();
    let target_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("target node")
        .id;
    let next_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Editable Nodes")
        .expect("next node")
        .id;
    let target_text = state.nodes[target_id].markdown.clone();
    let next_text = state.nodes[next_id].markdown.clone();

    state.set_selected(target_id);
    let join_offset = state.merge_next_into_selected().expect("merge next");

    assert_eq!(join_offset, target_text.len());
    assert_eq!(
        state.nodes[target_id].markdown,
        format!("{}{}", target_text, next_text)
    );
    assert_eq!(state.selected_node, Some(target_id));
}

#[test]
fn merge_next_into_selected_decreases_node_count() {
    let mut state = AppState::demo();
    let count_before = state.flattened_nodes().len();
    let target_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("target node")
        .id;
    state.set_selected(target_id);
    state.merge_next_into_selected().expect("merge");
    assert_eq!(state.flattened_nodes().len(), count_before - 1);
}

// ── Selection-highlighted propagation tests ───────────────────────────────────

#[test]
fn selection_highlighted_propagates_to_children() {
    let mut state = AppState::demo();
    // Select "Spec Tree Pane" which has children.
    let parent_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("parent node")
        .id;
    state.set_selected(parent_id);

    let flat = state.flattened_nodes();
    let parent_flat = flat
        .iter()
        .find(|n| n.id == parent_id)
        .expect("parent in flat");
    assert!(
        parent_flat.selection_highlighted,
        "parent itself must be highlighted"
    );

    // All children of parent_id should also be highlighted.
    for &child_id in &state.nodes[parent_id].children {
        let child_flat = flat
            .iter()
            .find(|n| n.id == child_id)
            .expect("child in flat");
        assert!(
            child_flat.selection_highlighted,
            "child {} should be highlighted",
            child_id
        );
    }
}

#[test]
fn selection_highlighted_false_for_unrelated_nodes() {
    let mut state = AppState::demo();
    let parent_id = state
        .nodes
        .iter()
        .find(|n| first_line(&n.markdown) == "Spec Tree Pane")
        .expect("node")
        .id;
    state.set_selected(parent_id);

    let flat = state.flattened_nodes();
    // "Execution Stream" is a sibling and should NOT be highlighted.
    let sibling = flat
        .iter()
        .find(|n| first_line(&n.markdown) == "Execution Stream")
        .expect("sibling in flat");
    assert!(!sibling.selection_highlighted);
}
