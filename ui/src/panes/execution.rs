use gpui::*;

use crate::app::state::AppState;

pub struct ExecutionPane;

impl ExecutionPane {
    pub fn bind_event_stream() -> &'static str {
        "stream connected"
    }

    pub fn render_box_inspector(state: &AppState) -> impl IntoElement {
        let selected = state.selected_spec_ref().unwrap_or("-");

        div()
            .flex()
            .flex_col()
            .gap_2()
            .child(
                div()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child("Execution + Box Inspector"),
            )
            .child(
                div()
                    .text_sm()
                    .child(format!("lineage: {selected}")),
            )
            .child(
                div()
                    .text_sm()
                    .child("No active run yet. This pane will stream AgentEvents and spec verification evidence."),
            )
    }

    pub fn render_spec_compliance(spec_ref: &str) -> String {
        format!("Spec compliance for {spec_ref}: pending")
    }
}
