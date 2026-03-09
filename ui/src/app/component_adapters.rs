use gpui::*;
use gpui_component::button::{Button, ButtonVariants};
use gpui_component::Sizable;

use super::actions::UiAction;
use super::AppShell;

pub fn render_chevron(
    collapsed: bool,
    has_children: bool,
    is_root: bool,
    node_id: crate::app::state::NodeId,
    cx: &mut Context<AppShell>,
) -> Option<gpui::AnyElement> {
    if !has_children || is_root {
        return None;
    }

    let chevron_icon = if collapsed { "▶" } else { "▼" };

    let button = Button::new(("chevron", node_id))
        .child(chevron_icon)
        .xsmall()
        .ghost()
        .text_color(gpui::rgb(0x9CA3AF)) // Light gray
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(move |this, _event, _window, cx| {
                this.apply(UiAction::SelectNode(node_id), cx);
                this.apply(UiAction::ToggleCollapse, cx);
            }),
        );

    Some(button.into_any_element())
}
