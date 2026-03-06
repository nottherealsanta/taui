use pretty_assertions::assert_eq;

use taui_ui::app::actions::{dispatch, UiAction};
use taui_ui::app::state::AppState;

#[test]
fn add_sibling_node_selects_new_node() {
    let mut state = AppState::demo();
    let before = state.flattened_nodes().len();

    let changed = dispatch(&mut state, UiAction::AddSiblingNode);

    assert!(changed);
    assert_eq!(state.flattened_nodes().len(), before + 1);
    let selected = state.selected_node.expect("selected node");
    assert_eq!(state.nodes[selected].title, "New Node");
    assert!(state.edit_mode);
}

#[test]
fn tab_indent_makes_previous_sibling_parent() {
    let mut state = AppState::demo();

    // Select the second child under "Spec Tree Pane".
    let target = state
        .nodes
        .iter()
        .find(|node| node.title == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));

    let changed = dispatch(&mut state, UiAction::IndentNode);

    assert!(changed);
    let selected = state.selected_node.expect("selected node");
    let parent = state.nodes[selected].parent.expect("has new parent");
    assert_eq!(state.nodes[parent].title, "Editable Nodes");
}

#[test]
fn shift_tab_outdents_node() {
    let mut state = AppState::demo();

    let target = state
        .nodes
        .iter()
        .find(|node| node.title == "Tab Indent")
        .expect("target node")
        .id;
    dispatch(&mut state, UiAction::SelectNode(target));
    dispatch(&mut state, UiAction::IndentNode);

    let changed = dispatch(&mut state, UiAction::OutdentNode);

    assert!(changed);
    let selected = state.selected_node.expect("selected node");
    let parent = state.nodes[selected].parent.expect("has parent");
    assert_eq!(state.nodes[parent].title, "Spec Tree Pane");
}
