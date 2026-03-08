pub mod actions;
pub mod keybindings;
pub mod state;

use gpui::InteractiveElement;
use gpui::*;

use crate::panes::{
    chat::ChatPane, execution::ExecutionPane, plan_status::PlanStatusPane, spec_tree::SpecTreePane,
};
use crate::theme::ThemeRegistry;

use self::actions::{dispatch, UiAction};
use self::state::{AppState, FlatNode, NodeStatus};

pub fn run() {
    let app = Application::new();

    app.run(move |cx| {
        cx.spawn(async move |cx| {
            cx.open_window(WindowOptions::default(), |_window, cx| {
                cx.new(|cx| AppShell::new(cx))
            })?;

            Ok::<_, anyhow::Error>(())
        })
        .detach();
    });
}

pub struct AppShell {
    state: AppState,
    focus_handle: FocusHandle,
    theme: crate::theme::Theme,
}

impl AppShell {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let theme = ThemeRegistry::new()
            .default_dark()
            .expect("at least one dark theme is required");

        Self {
            state: AppState::demo(),
            focus_handle: cx.focus_handle(),
            theme,
        }
    }

    fn apply(&mut self, action: UiAction, cx: &mut Context<Self>) {
        if dispatch(&mut self.state, action) {
            cx.notify();
        }
    }

    fn status_color(&self, status: NodeStatus) -> Rgba {
        let s = self.theme.styles.status;
        match status {
            NodeStatus::Draft => rgb(s.spec_draft),
            NodeStatus::Ready => rgb(s.spec_ready),
            NodeStatus::InProgress => rgb(s.spec_in_progress),
            NodeStatus::Done => rgb(s.spec_done),
            NodeStatus::Blocked => rgb(s.spec_blocked),
        }
    }

    fn handle_key_down(&mut self, event: &KeyDownEvent, cx: &mut Context<Self>) {
        if let Some(action) = keybindings::map_key_to_action(&event.keystroke) {
            self.apply(action, cx);
        }
    }

    fn render_spec_row(&self, row: &FlatNode, cx: &mut Context<Self>) -> impl IntoElement {
        let colors = self.theme.styles.colors;
        let selected = row.selected;
        let node_id = row.id;

        let title = if selected && self.state.edit_mode {
            format!("{} |", row.title)
        } else {
            row.title.clone()
        };

        let label_color = if selected {
            rgb(colors.text)
        } else {
            rgb(colors.text_muted)
        };

        let row_bg = if selected {
            rgb(colors.element_selected)
        } else {
            rgb(colors.panel_background)
        };

        let indent_guides = div()
            .flex()
            .items_center()
            .gap_1()
            .children((0..row.depth).map(|_| {
                div()
                    .w(px(10.0))
                    .h(px(18.0))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child(div().w(px(1.0)).h_full().bg(rgb(colors.border_variant)))
            }));

        let row_el = div()
            .w_full()
            .flex()
            .items_center()
            .justify_between()
            .gap_2()
            .px_2()
            .py_1()
            .bg(row_bg)
            .rounded(px(4.0))
            .cursor_pointer()
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap_2()
                    .flex_1()
                    .child(indent_guides)
                    .child(div().flex_1().text_color(label_color).child(title)),
            )
            .child(
                div()
                    .text_xs()
                    .px_2()
                    .py_0p5()
                    .rounded(px(999.0))
                    .bg(rgb(0x000000))
                    .text_color(self.status_color(row.status))
                    .child(SpecTreePane::render_node_status(row.status)),
            );

        let row_el = row_el.on_mouse_down(
            MouseButton::Left,
            cx.listener(move |this, _event, _window, cx| {
                this.apply(UiAction::SelectNode(node_id), cx);
            }),
        );

        row_el
    }
}

impl Render for AppShell {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let colors = self.theme.styles.colors;
        let spec_rows = SpecTreePane::render_tree(&self.state);
        let selected_ref =
            SpecTreePane::select_spec_ref(&self.state).unwrap_or_else(|| "-".to_string());

        let root = div()
            .size_full()
            .bg(rgb(colors.background))
            .text_color(rgb(colors.text))
            .track_focus(&self.focus_handle);
        let root = root.on_mouse_down(
            MouseButton::Left,
            cx.listener(|this, _event, window, _cx| {
                this.focus_handle.focus(window);
            }),
        );
        let root = root.on_key_down(cx.listener(|this, event, _window, cx| {
            this.handle_key_down(event, cx);
        }));

        root
            .child(
                div()
                    .h(px(52.0))
                    .px_4()
                    .flex()
                    .items_center()
                    .justify_between()
                    .bg(rgb(colors.panel_background))
                    .border_b_1()
                    .border_color(rgb(colors.border))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap_3()
                            .child(
                                div()
                                    .text_lg()
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .child("Taui UI"),
                            )
                            .child(
                                div()
                                    .text_sm()
                                    .text_color(rgb(colors.text_muted))
                                    .child("spec-first desktop interface"),
                            ),
                    )
                    .child(
                        div()
                            .text_sm()
                            .text_color(rgb(colors.text_accent))
                            .child(format!("selected: {selected_ref}")),
                    ),
            )
            .child(
                div()
                    .flex()
                    .flex_1()
                    .h_full()
                    .child(
                        div()
                            .w(px(360.0))
                            .h_full()
                            .flex()
                            .flex_col()
                            .border_r_1()
                            .border_color(rgb(colors.border))
                            .bg(rgb(colors.panel_background))
                            .child(
                                div()
                                    .flex_1()
                                    .p_3()
                                    .border_b_1()
                                    .border_color(rgb(colors.border_variant))
                                    .child(ExecutionPane::render_box_inspector(&self.state)),
                            )
                            .child(
                                div()
                                    .flex_1()
                                    .p_3()
                                    .child(PlanStatusPane::render_task_graph(&self.state)),
                            ),
                    )
                    .child(
                        div()
                            .flex_1()
                            .h_full()
                            .p_3()
                            .bg(rgb(colors.panel_background))
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .justify_between()
                                    .mb_2()
                                    .child(
                                        div()
                                            .font_weight(FontWeight::SEMIBOLD)
                                            .child("Spec Tree"),
                                    )
                                    .child(
                                        {
                                            let add_node_button = div()
                                                .px_2()
                                                .py_1()
                                                .rounded(px(4.0))
                                                .bg(rgb(colors.element_background))
                                                .cursor_pointer()
                                                .child("+ Node");
                                            let add_node_button = add_node_button.on_mouse_down(
                                                MouseButton::Left,
                                                cx.listener(|this, _event, _window, cx| {
                                                    this.apply(UiAction::AddSiblingNode, cx);
                                                }),
                                            );
                                            add_node_button
                                        },
                                    ),
                            )
                            .child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .w_full()
                                    .children(spec_rows.into_iter().map(|row| {
                                        self.render_spec_row(&row, cx)
                                    })),
                            )
                            .child(
                                div()
                                    .mt_3()
                                    .p_2()
                                    .rounded(px(6.0))
                                    .bg(rgb(colors.elevated_surface_background))
                                    .text_sm()
                                    .text_color(rgb(colors.text_muted))
                                    .child("Keys: Enter new node, Tab indent child, Shift+Tab outdent, Ctrl+S cycle status"),
                            ),
                    )
                    .child(
                        div()
                            .w(px(360.0))
                            .h_full()
                            .p_3()
                            .border_l_1()
                            .border_color(rgb(colors.border))
                            .bg(rgb(colors.panel_background))
                            .child(
                                ChatPane::render(&self.state),
                            ),
                    ),
            )
    }
}
