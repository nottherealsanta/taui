use gpui::*;

use crate::app::state::AppState;

pub struct PlanStatusPane;

impl PlanStatusPane {
    pub fn render_task_graph(state: &AppState) -> impl IntoElement {
        let count = state.flattened_nodes().len();
        div()
            .flex()
            .flex_col()
            .gap_2()
            .child(
                div()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child("Plan / Status"),
            )
            .child(div().text_sm().child(format!("nodes in graph: {count}")))
            .child(div().text_sm().child("DAG rendering scaffold in place."))
    }

    pub fn render_task_node(label: &str) -> String {
        format!("task: {label}")
    }

    pub fn highlight_active_wave(wave: usize) -> String {
        format!("active wave: {wave}")
    }
}
