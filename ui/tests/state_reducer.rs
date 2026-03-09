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
