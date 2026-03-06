use crate::app::state::{AppState, FlatNode, NodeStatus};

pub struct SpecTreePane;

impl SpecTreePane {
    pub fn render_tree(state: &AppState) -> Vec<FlatNode> {
        state.flattened_nodes()
    }

    pub fn select_spec_ref(state: &AppState) -> Option<String> {
        state.selected_spec_ref().map(ToString::to_string)
    }

    pub fn render_node_status(status: NodeStatus) -> &'static str {
        match status {
            NodeStatus::Draft => "draft",
            NodeStatus::Ready => "ready",
            NodeStatus::InProgress => "in_progress",
            NodeStatus::Done => "done",
            NodeStatus::Blocked => "blocked",
        }
    }

    pub fn render_clarification(blocking: bool) -> &'static str {
        if blocking {
            "blocking clarification"
        } else {
            "non-blocking clarification"
        }
    }

    pub fn render_amendment(accepted: Option<bool>) -> &'static str {
        match accepted {
            Some(true) => "amendment accepted",
            Some(false) => "amendment rejected",
            None => "amendment proposed",
        }
    }
}
