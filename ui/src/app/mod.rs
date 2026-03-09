pub mod actions;
pub mod component_adapters;
pub mod keybindings;
pub mod state;
pub mod typography;

use gpui::prelude::FluentBuilder;
use gpui::Focusable;
use gpui::FontWeight;
use gpui::InteractiveElement;
use gpui::*;
use gpui_component::input::{Input, InputEvent, InputState};
use gpui_component::scroll::ScrollableElement;
use gpui_component::text::TextView;
use gpui_component::TitleBar;

use crate::services::backend_client::BackendClient;
use crate::theme::ThemeRegistry;

use self::actions::{dispatch, UiAction};
use self::state::{AppState, BackendNode, BackendState, FlatNode, NodeId};
use self::typography::{
    markdown_edit_style, markdown_view_style, split_root_markdown, INDENT_PER_LEVEL,
    MARKDOWN_LINE_HEIGHT, MARKDOWN_TEXT_SIZE, MAX_CONTENT_WIDTH,
};

pub fn run() {
    let rt = tokio::runtime::Runtime::new().expect("failed to create tokio runtime");
    let _guard = rt.enter();

    let app = Application::new();

    app.run(move |cx| {
        gpui_component::init(cx);

            cx.spawn(async move |cx| {
            let options = WindowOptions {
                titlebar: Some(TitleBar::title_bar_options()),
                ..Default::default()
            };

            cx.open_window(options, |window, cx| {
                let app_shell = cx.new(|cx| AppShell::new(window, cx));
                cx.new(|cx| gpui_component::Root::new(app_shell, window, cx))
            })?;

            Ok::<_, anyhow::Error>(())
        })
        .detach();
    });
}

pub struct AppShell {
    state: AppState,
    focus_handle: FocusHandle,
    theme_registry: ThemeRegistry,
    theme: crate::theme::Theme,
    client: Option<BackendClient>,
    markdown_input: Entity<InputState>,
    editing_node_id: Option<NodeId>,
    saved_markdown: String,
    _subscriptions: Vec<gpui::Subscription>,
    last_window_title: String,
    tree_scroll_handle: UniformListScrollHandle,
    cached_markdown_style: Option<gpui_component::text::TextViewStyle>,
    cached_flat_tree: Vec<FlatNode>,
    flat_tree_dirty: bool,
}

impl AppShell {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let theme_registry = ThemeRegistry::new();
        let theme = theme_registry
            .default_for_dark_mode(Self::is_dark_window_appearance(window.appearance()))
            .or_else(|| theme_registry.default_light())
            .or_else(|| theme_registry.default_dark())
            .expect("at least one bundled theme is required");

        let ws_url = std::env::var("TAUI_BACKEND_WS")
            .unwrap_or_else(|_| "ws://127.0.0.1:8000/ws".to_string());

        let mut state = AppState::demo();
        state.backend_state = BackendState::Loading;

        let client = BackendClient::new(ws_url.clone());
        let client_for_bootstrap = client.clone();

        let markdown_input = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Markdown...")
                .multi_line(true)
                .auto_grow(3, 20)
                .soft_wrap(true)
        });

        cx.spawn(async move |this, cx| {
            let tree_result = async {
                client_for_bootstrap.initialize(None).await?;
                client_for_bootstrap.get_tree_detailed().await
            }
            .await;

            this.update(cx, |shell, cx| {
                match tree_result {
                    Ok(tree_response) => {
                        let backend_nodes: Vec<BackendNode> = tree_response
                            .nodes
                            .into_iter()
                            .map(|n| BackendNode {
                                spec_ref: n.spec_ref,
                                depth: n.depth,
                                markdown: n.markdown,
                            })
                            .collect();
                        shell.state.hydrate_from_backend(backend_nodes);
                        shell.mark_flat_tree_dirty();
                        shell.client = Some(client);
                    }
                    Err(e) => {
                        shell.state.backend_state = BackendState::Error(e.to_string());
                    }
                }
                cx.notify();
            })
        })
        .detach();

        let mut shell = Self {
            state,
            focus_handle: cx.focus_handle(),
            theme_registry,
            theme,
            client: None,
            markdown_input: markdown_input.clone(),
            editing_node_id: None,
            saved_markdown: String::new(),
            _subscriptions: Vec::new(),
            last_window_title: String::new(),
            tree_scroll_handle: UniformListScrollHandle::new(),
            cached_markdown_style: None,
            cached_flat_tree: Vec::new(),
            flat_tree_dirty: true,
        };

        let blur_subscription = cx.subscribe_in(
            &markdown_input,
            window,
            |this, _state, event, _window, cx| match event {
                InputEvent::Blur => this.auto_save_markdown(cx),
                InputEvent::Change => this.sync_editing_markdown_preview(cx),
                _ => {}
            },
        );
        shell._subscriptions.push(blur_subscription);

        let appearance_subscription = cx.observe_window_appearance(window, |this, window, cx| {
            this.sync_theme_from_window_appearance(window.appearance());
            cx.notify();
        });
        shell._subscriptions.push(appearance_subscription);

        shell
    }

    fn is_dark_window_appearance(appearance: WindowAppearance) -> bool {
        matches!(
            appearance,
            WindowAppearance::Dark | WindowAppearance::VibrantDark
        )
    }

    fn sync_theme_from_window_appearance(&mut self, appearance: WindowAppearance) {
        if let Some(theme) = self
            .theme_registry
            .default_for_dark_mode(Self::is_dark_window_appearance(appearance))
        {
            self.theme = theme;
            // Invalidate cached markdown style when theme changes
            self.cached_markdown_style = None;
        }
    }

    fn get_markdown_style(&mut self) -> gpui_component::text::TextViewStyle {
        if self.cached_markdown_style.is_none() {
            self.cached_markdown_style = Some(markdown_view_style(self.is_dark_theme()));
        }
        self.cached_markdown_style.clone().unwrap()
    }

    fn get_flat_tree(&mut self) -> &Vec<FlatNode> {
        if self.flat_tree_dirty {
            self.cached_flat_tree = self.state.flattened_tree_nodes();
            self.flat_tree_dirty = false;
        }
        &self.cached_flat_tree
    }

    fn mark_flat_tree_dirty(&mut self) {
        self.flat_tree_dirty = true;
    }

    fn sync_window_title(&mut self, window: &mut Window) {
        if let Some(root_id) = self.state.primary_root_id() {
            let root_markdown = &self.state.nodes[root_id].markdown;
            let (title, _) = split_root_markdown(root_markdown);
            let new_title = if title.is_empty() {
                "Taui".to_string()
            } else {
                title
            };

            if new_title != self.last_window_title {
                window.set_window_title(&new_title);
                self.last_window_title = new_title;
            }
        }
    }

    fn get_root_title(&self) -> String {
        // Use cached window title if available, otherwise compute it
        if !self.last_window_title.is_empty() {
            return self.last_window_title.clone();
        }
        
        if let Some(root_id) = self.state.primary_root_id() {
            let root_markdown = &self.state.nodes[root_id].markdown;
            let (title, _) = split_root_markdown(root_markdown);
            if title.is_empty() {
                "Taui".to_string()
            } else {
                title
            }
        } else {
            "Taui".to_string()
        }
    }

    fn is_dark_theme(&self) -> bool {
        matches!(self.theme.appearance, crate::theme::Appearance::Dark)
    }

    fn apply(&mut self, action: UiAction, cx: &mut Context<Self>) {
        // Check if this is a structural change before dispatching
        let is_structural = matches!(action, UiAction::AddSiblingNode | UiAction::IndentNode | UiAction::OutdentNode | UiAction::ToggleCollapse);
        
        if dispatch(&mut self.state, action) {
            if is_structural {
                self.mark_flat_tree_dirty();
            }
            cx.notify();
        }
    }

    fn apply_structural(&mut self, action: UiAction, cx: &mut Context<Self>) {
        let Some(client) = self.client.clone() else {
            self.apply(action, cx);
            return;
        };

        let selected_ref = self.state.selected_spec_ref().map(|s| s.to_string());
        let Some(spec_ref) = selected_ref else {
            self.apply(action, cx);
            return;
        };

        cx.spawn(async move |this, cx| {
            let rpc_result: anyhow::Result<()> = async {
                match &action {
                    UiAction::AddSiblingNode => {
                        client.create_sibling_node(&spec_ref).await?;
                    }
                    UiAction::IndentNode => {
                        client.indent_node(&spec_ref).await?;
                    }
                    UiAction::OutdentNode => {
                        client.outdent_node(&spec_ref).await?;
                    }
                    _ => {}
                }
                Ok(())
            }
            .await;

            let tree_result = client.get_tree_detailed().await;

            this.update(&mut *cx, |shell, cx| {
                if let Err(e) = rpc_result {
                    shell.state.backend_state = BackendState::Error(e.to_string());
                    cx.notify();
                    return;
                }

                match tree_result {
                    Ok(tree_response) => {
                        let backend_nodes: Vec<BackendNode> = tree_response
                            .nodes
                            .into_iter()
                            .map(|n| BackendNode {
                                spec_ref: n.spec_ref,
                                depth: n.depth,
                                markdown: n.markdown,
                            })
                            .collect();
                        shell.state.hydrate_from_backend(backend_nodes);
                        shell.mark_flat_tree_dirty();
                    }
                    Err(e) => {
                        shell.state.backend_state = BackendState::Error(e.to_string());
                    }
                }
                cx.notify();
            })
        })
        .detach();
    }

    fn auto_save_markdown(&mut self, cx: &mut Context<Self>) {
        let Some(node_id) = self.editing_node_id else {
            return;
        };
        let new_markdown = self.markdown_input.read(cx).value().to_string();

        if new_markdown != self.saved_markdown {
            let markdown = new_markdown.clone();

            self.state.nodes[node_id].markdown = markdown.clone();
            self.saved_markdown = new_markdown;

            if let Some(client) = self.client.clone() {
                let spec_ref = self.state.nodes[node_id].spec_ref.clone();

                cx.spawn(async move |this, cx| {
                    let patch = serde_json::json!({
                        "markdown": markdown
                    });
                    let result = client.update_node(&spec_ref, patch).await;
                    this.update(cx, |shell, cx| {
                        if let Err(e) = result {
                            shell.state.backend_state =
                                BackendState::Error(format!("Update failed: {}", e));
                        }
                        cx.notify();
                    })
                })
                .detach();
            }
        }
    }

    fn save_current_edits(&mut self, cx: &mut Context<Self>) {
        self.auto_save_markdown(cx);
    }

    fn sync_editing_markdown_preview(&mut self, cx: &mut Context<Self>) {
        let Some(node_id) = self.editing_node_id else {
            return;
        };
        let Some(node) = self.state.nodes.get_mut(node_id) else {
            return;
        };
        let new_markdown = self.markdown_input.read(cx).value().to_string();
        if node.markdown != new_markdown {
            node.markdown = new_markdown.clone();
            // Update the cached flat tree entry for this node
            if let Some(flat_node) = self.cached_flat_tree.iter_mut().find(|n| n.id == node_id) {
                flat_node.markdown = new_markdown;
            }
            cx.notify();
        }
    }

    fn select_node(&mut self, node_id: NodeId, window: &mut Window, cx: &mut Context<Self>) {
        self.save_current_edits(cx);

        self.state.set_selected(node_id);
        self.editing_node_id = Some(node_id);

        let node = &self.state.nodes[node_id];
        let markdown = node.markdown.clone();

        self.saved_markdown = markdown.clone();

        self.markdown_input.update(cx, |state, cx| {
            state.set_value(&markdown, window, cx);
        });

        cx.notify();
    }

    fn is_input_focused(&self, window: &Window, cx: &App) -> bool {
        let handle = self.markdown_input.read(cx).focus_handle(cx);
        handle.is_focused(window)
    }

    fn handle_key_down(
        &mut self,
        event: &KeyDownEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let keystroke = &event.keystroke;
        let key = keystroke.key.to_string().to_ascii_lowercase();

        if key == "tab" {
            self.save_current_edits(cx);
            if keystroke.modifiers.shift {
                self.apply_structural(UiAction::OutdentNode, cx);
            } else {
                self.apply_structural(UiAction::IndentNode, cx);
            }
            return;
        }

        let input_focused = self.is_input_focused(window, cx);

        if input_focused {
            match key.as_str() {
                "escape" => {
                    self.save_current_edits(cx);
                    self.focus_handle.focus(window);
                    cx.notify();
                }
                _ => {}
            }
            return;
        }

        if let Some(action) = keybindings::map_key_to_action(&event.keystroke) {
            match &action {
                UiAction::AddSiblingNode | UiAction::IndentNode | UiAction::OutdentNode => {
                    self.apply_structural(action, cx);
                }
                UiAction::SelectNode(node_id) => {
                    self.select_node(*node_id, window, cx);
                    self.markdown_input.update(cx, |state, cx| {
                        state.focus(window, cx);
                    });
                }
                UiAction::SelectNext | UiAction::SelectPrevious => {
                    self.apply(action, cx);
                    if let Some(selected) = self.state.selected_node {
                        self.select_node(selected, window, cx);
                    }
                }
                UiAction::ToggleCollapse => {
                    self.apply(action, cx);
                    if let Some(client) = self.client.clone() {
                        if let Some(selected) = self.state.selected_node {
                            let markdown = self.state.nodes[selected].markdown.clone();
                            let spec_ref = self.state.nodes[selected].spec_ref.clone();

                            cx.spawn(async move |this, cx| {
                                let patch = serde_json::json!({
                                    "markdown": markdown
                                });
                                let result = client.update_node(&spec_ref, patch).await;
                                this.update(cx, |shell, cx| {
                                    if let Err(e) = result {
                                        shell.state.backend_state =
                                            BackendState::Error(format!("Update failed: {}", e));
                                    }
                                    cx.notify();
                                })
                            })
                            .detach();
                        }
                    }
                }
            }
        }
    }

    fn render_row(
        &mut self,
        row: &FlatNode,
        is_root: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> impl IntoElement {
        let selected = row.selected;
        let node_id = row.id;
        let row_has_children = row.has_children;
        let row_depth = row.depth;
        let colors = self.theme.styles.colors.clone();

        let indent_width = INDENT_PER_LEVEL * row_depth as f32;

        // Chevron for expand/collapse - hidden for root, rendered for other nodes with children
        let chevron: Option<gpui::AnyElement> = 
            component_adapters::render_chevron(row.collapsed, row_has_children, is_root, node_id, cx);

        // Bullet marker - always shown, slightly larger and darker gray
        let bullet = div()
            .child("•")
            .text_color(rgb(colors.text)) // Darker gray (use main text color)
            .text_size(px(18.0)); // Slightly larger than body text (MARKDOWN_TEXT_SIZE is 16px)

        // Left controls: chevron (if any) + bullet
        let left_controls = div()
            .flex()
            .items_center()
            .gap_1()
            .when_some(chevron, |this, c| this.child(c))
            .child(bullet);

        let indent_guides = if !is_root && row_depth > 0 {
            Some(
                div()
                    .absolute()
                    .left(px(8.0))
                    .top_0()
                    .bottom_0()
                    .w(indent_width)
                    .flex()
                    .children((0..row_depth).map(|i| {
                        let x_pos = INDENT_PER_LEVEL * i as f32;
                        div()
                            .absolute()
                            .left(x_pos)
                            .top_0()
                            .bottom_0()
                            .w(px(1.0))
                            .bg(rgb(colors.border_variant))
                    })),
            )
        } else {
            None
        };

        let is_active_editor = selected && self.editing_node_id == Some(node_id);
        let markdown = if row.markdown.trim().is_empty() {
            " ".to_string()
        } else {
            row.markdown.clone()
        };

        // Content area - now separate from left controls
        let content_area = if is_active_editor {
            let markdown_input = self.markdown_input.clone();
            let editor_markdown = self.markdown_input.read(cx).value().to_string();
            let (editor_text_size, editor_weight) = markdown_edit_style(&editor_markdown);
            div()
                .flex_1()
                .child(
                    Input::new(&markdown_input)
                        .appearance(false)
                        .bordered(false)
                        .px(px(0.0))
                        .py(px(0.0))
                        .text_size(editor_text_size)
                        .font_weight(editor_weight)
                        .line_height(relative(MARKDOWN_LINE_HEIGHT)),
                )
        } else {
            let markdown_view_id = ("node-markdown", node_id);
            let markdown_style = self.get_markdown_style();
            div()
                .flex_1()
                .cursor_pointer()
                .on_mouse_down(
                    MouseButton::Left,
                    cx.listener(move |this, _event, window, cx| {
                        this.select_node(node_id, window, cx);
                        this.markdown_input.update(cx, |state, cx| {
                            state.focus(window, cx);
                        });
                    }),
                )
                .child(
                    TextView::markdown(markdown_view_id, markdown, window, cx)
                        .style(markdown_style)
                        .text_size(MARKDOWN_TEXT_SIZE)
                        .line_height(relative(MARKDOWN_LINE_HEIGHT))
                        .text_color(rgb(colors.text)),
                )
        };

        let padding = if is_root {
            (px(14.0), px(10.0))
        } else {
            (px(10.0), px(5.0))
        };

        let mut row_el = div()
            .relative()
            .w_full()
            .max_w(MAX_CONTENT_WIDTH)
            .flex()
            .flex_col()
            .px(padding.0)
            .py(padding.1)
            .when(selected, |this| {
                this.border_l_2().border_color(rgb(colors.border))
            });

        // Row layout: indent guides + [left_controls + content_area] in horizontal flex
        row_el = row_el.children(indent_guides).child(
            div()
                .pl(if is_root { px(0.0) } else { indent_width })
                .flex()
                .items_center()
                .gap_1()
                .child(left_controls)
                .child(content_area),
        );

        row_el
    }
}

impl Render for AppShell {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        self.sync_window_title(window);

        let spec_rows = self.get_flat_tree().clone();
        let colors = self.theme.styles.colors.clone();
        let status = self.theme.styles.status.clone();

        let root = div()
            .size_full()
            .bg(rgb(colors.background))
            .text_color(rgb(colors.text))
            .track_focus(&self.focus_handle);

        let root = root.on_key_down(cx.listener(|this, event, window, cx| {
            this.handle_key_down(event, window, cx);
        }));

        let status_banner: Option<gpui::AnyElement> = match &self.state.backend_state {
            BackendState::Loading => Some(
                div()
                    .w_full()
                    .px_3()
                    .py_1()
                    .rounded(px(4.0))
                    .bg(rgb(colors.element_background))
                    .text_color(rgb(colors.text_muted))
                    .text_xs()
                    .child("Connecting to backend...")
                    .into_any_element(),
            ),
            BackendState::Error(msg) => {
                let msg = msg.clone();
                Some(
                    div()
                        .w_full()
                        .px_3()
                        .py_1()
                        .rounded(px(4.0))
                        .bg(rgb(colors.element_background))
                        .text_color(rgb(status.error))
                        .text_xs()
                        .child(format!("Backend error: {} - showing demo data", msg))
                        .into_any_element(),
                )
            }
            BackendState::Offline => Some(
                div()
                    .w_full()
                    .px_3()
                    .py_1()
                    .rounded(px(4.0))
                    .bg(rgb(colors.element_background))
                    .text_color(rgb(colors.text_muted))
                    .text_xs()
                    .child("Offline - demo data")
                    .into_any_element(),
            ),
            BackendState::Ready => None,
        };

        let root_id = self.state.primary_root_id();
        let root_title = self.get_root_title();

        // Create root row with body only (skip first line/title)
        let root_row = root_id.map(|id| {
            let node = &self.state.nodes[id];
            let (_, body) = split_root_markdown(&node.markdown);
            FlatNode {
                id,
                depth: 0,
                markdown: body,
                selected: self.state.selected_node == Some(id),
                collapsed: node.collapsed,
                has_children: !node.children.is_empty(),
            }
        });

        let titlebar = TitleBar::new()
            .child(
                div()
                    .ml_12()
                    .flex()
                    .items_center()
                    .h_full()
                    .child(
                        div()
                            .text_base()
                            .font_weight(FontWeight::BOLD)
                            .child(root_title),
                    ),
            );

        root
            .child(titlebar)
            .child(
                div()
                    .w_full()
                    .flex_1()
                    .flex()
                    .justify_center()
                    .items_start()
                    .overflow_y_scrollbar()
                    .child(
                        div()
                            .w_full()
                            .max_w_full()
                            .max_w(MAX_CONTENT_WIDTH)
                            .px_3()
                            .py_3()
                            .flex()
                            .flex_col()
                            .items_center()
                            .gap_1()
                            .children(status_banner)
                            .children(root_row.map(|row| self.render_row(&row, true, window, cx)))
                            .when(root_id.is_some(), |this| {
                                this.child(div().w_full().border_t_1().border_color(rgb(colors.border)))
                            })
                            .children(spec_rows.into_iter().filter_map(|row| {
                                if root_id == Some(row.id) {
                                    None
                                } else {
                                    Some(self.render_row(&row, false, window, cx))
                                }
                            })),
                    ),
            )
    }
}
