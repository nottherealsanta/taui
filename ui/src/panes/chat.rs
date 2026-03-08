use gpui::*;

use crate::app::state::AppState;

pub struct ChatPane;

impl ChatPane {
    pub fn render(state: &AppState) -> impl IntoElement {
        div()
            .flex()
            .flex_col()
            .gap_2()
            .child(
                div()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child("Chat / Steering"),
            )
            .child(
                div()
                    .text_sm()
                    .child(format!("target: {}", state.chat_target)),
            )
            .child(
                div()
                    .text_sm()
                    .child("Secondary escape hatch. Use spec tree first."),
            )
    }

    pub fn submit_message(message: &str) -> String {
        format!("queued: {message}")
    }

    pub fn set_target_agent(target: &str) -> String {
        format!("target set to {target}")
    }
}
