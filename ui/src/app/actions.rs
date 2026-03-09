use super::state::{AppState, NodeId, SpecRef};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UiAction {
    SelectNode(NodeId),
    SelectNext,
    SelectPrevious,
    AddSiblingNode,
    IndentNode,
    OutdentNode,
    ToggleCollapse,
}

pub fn dispatch(state: &mut AppState, action: UiAction) -> bool {
    match action {
        UiAction::SelectNode(node_id) => {
            if state.selected_node == Some(node_id) {
                return false;
            }
            state.set_selected(node_id);
            true
        }
        UiAction::SelectNext => move_selection(state, 1),
        UiAction::SelectPrevious => move_selection(state, -1),
        UiAction::AddSiblingNode => add_sibling_node(state),
        UiAction::IndentNode => indent_selected(state),
        UiAction::OutdentNode => outdent_selected(state),
        UiAction::ToggleCollapse => state.toggle_collapse(),
    }
}

fn move_selection(state: &mut AppState, delta: isize) -> bool {
    let flattened = state.flattened_nodes();
    if flattened.is_empty() {
        return false;
    }

    let current = state
        .selected_node
        .and_then(|selected| flattened.iter().position(|row| row.id == selected))
        .unwrap_or(0);

    let target = if delta.is_negative() {
        current.saturating_sub(delta.unsigned_abs())
    } else {
        let next = current.saturating_add(delta as usize);
        next.min(flattened.len() - 1)
    };

    if current == target {
        return false;
    }

    state.set_selected(flattened[target].id);
    true
}

fn add_sibling_node(state: &mut AppState) -> bool {
    let parent = state
        .selected_node
        .and_then(|selected| state.nodes[selected].parent);

    // Generate a temporary spec_ref; will be replaced by backend on next sync.
    let tmp_ref: SpecRef = format!("local/new-{}", state.nodes.len());

    let new_id = state.create_node(tmp_ref, String::new(), parent);

    let insertion_index = if let Some(selected) = state.selected_node {
        state
            .siblings(parent)
            .iter()
            .position(|id| *id == selected)
            .map(|idx| idx + 1)
            .unwrap_or_else(|| state.siblings(parent).len())
    } else {
        state.siblings(parent).len()
    };

    state.siblings_mut(parent).insert(insertion_index, new_id);
    state.selected_node = Some(new_id);
    true
}

fn indent_selected(state: &mut AppState) -> bool {
    let Some(selected) = state.selected_node else {
        return false;
    };

    let parent = state.nodes[selected].parent;
    let sibling_snapshot = state.siblings(parent).to_vec();

    let Some(index) = sibling_snapshot.iter().position(|id| *id == selected) else {
        return false;
    };

    if index == 0 {
        return false;
    }

    let new_parent = sibling_snapshot[index - 1];

    state.siblings_mut(parent).remove(index);
    state.nodes[selected].parent = Some(new_parent);
    state.nodes[new_parent].children.push(selected);
    true
}

fn outdent_selected(state: &mut AppState) -> bool {
    let Some(selected) = state.selected_node else {
        return false;
    };

    let Some(parent) = state.nodes[selected].parent else {
        return false;
    };

    let grand_parent = state.nodes[parent].parent;

    let Some(index_in_parent) = state.nodes[parent]
        .children
        .iter()
        .position(|id| *id == selected)
    else {
        return false;
    };

    state.nodes[parent].children.remove(index_in_parent);

    let parent_index = state
        .siblings(grand_parent)
        .iter()
        .position(|id| *id == parent)
        .map(|idx| idx + 1)
        .unwrap_or_else(|| state.siblings(grand_parent).len());

    state
        .siblings_mut(grand_parent)
        .insert(parent_index, selected);
    state.nodes[selected].parent = grand_parent;
    true
}
