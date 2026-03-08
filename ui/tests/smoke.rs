use taui_ui::app::state::AppState;

#[test]
fn demo_state_boots_with_selection_and_spec_ref() {
    let state = AppState::demo();

    assert!(state.selected_node.is_some());
    assert!(state.selected_spec_ref().is_some());
    assert!(!state.flattened_nodes().is_empty());
}
