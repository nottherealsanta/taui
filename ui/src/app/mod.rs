pub mod actions;
pub mod component_adapters;
pub mod keybindings;
pub mod state;
pub mod typography;

use gpui::prelude::FluentBuilder;
use gpui::Focusable;
use gpui::InteractiveElement;
use gpui::*;
use gpui_component::input::{
    Enter as InputEnter, IndentInline, Input, InputEvent, InputState, OutdentInline,
};
use gpui_component::text::TextView;
use gpui_component::TitleBar;

use crate::services::backend_client::{BackendClient, CodeRefPreview, ServerNotification};
use crate::theme::ThemeRegistry;

use self::actions::{dispatch, UiAction};
use self::state::{AgentDetailEvent, AgentState, AgentTier, AppState, BackendNode, BackendState, EditorMode, FlatNode, MetadataEditTarget, NodeId, PendingQuestion};
use self::typography::{
    depth_to_heading_style, markdown_edit_style, markdown_view_style, split_root_markdown,
    BODY_FONT_FAMILY, CODE_FONT_FAMILY, INDENT_PER_LEVEL, MARKDOWN_LINE_HEIGHT, MARKDOWN_TEXT_SIZE,
    MAX_CONTENT_WIDTH,
};

pub fn run() {
    let rt = tokio::runtime::Runtime::new().expect("failed to create tokio runtime");
    let _guard = rt.enter();

    let app = Application::new();

    app.run(move |cx| {
        gpui_component::init(cx);

        // Load custom fonts
        let font_data: Vec<std::borrow::Cow<'static, [u8]>> = vec![
            // IBM Plex Sans
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/ibm-plex-sans/IBMPlexSans-Regular.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/ibm-plex-sans/IBMPlexSans-Medium.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/ibm-plex-sans/IBMPlexSans-SemiBold.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/ibm-plex-sans/IBMPlexSans-Bold.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/ibm-plex-sans/IBMPlexSans-Italic.ttf")),
            // JetBrains Mono
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/jetbrains-mono/JetBrainsMono-Regular.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/jetbrains-mono/JetBrainsMono-Medium.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/jetbrains-mono/JetBrainsMono-Bold.ttf")),
            std::borrow::Cow::Borrowed(include_bytes!("../../assets/fonts/jetbrains-mono/JetBrainsMono-Italic.ttf")),
        ];
        cx.text_system().add_fonts(font_data).expect("failed to load custom fonts");

            cx.spawn(async move |cx| {
            let options = WindowOptions {
                titlebar: Some(TitleBar::title_bar_options()),
                focus: true,
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
    tree_scroll_handle: ScrollHandle,
    cached_markdown_style: Option<gpui_component::text::TextViewStyle>,
    /// Flat list of non-root tree rows, rebuilt only when `flat_tree_dirty` is set.
    cached_flat_tree: Vec<FlatNode>,
    flat_tree_dirty: bool,
    /// Cached body portion of the root node's markdown (title is shown in title bar).
    /// Invalidated together with the flat tree since root markdown changes are structural too.
    cached_root_body: Option<(NodeId, String)>,
    /// Resolved code ref previews keyed by node id.
    code_ref_previews: std::collections::HashMap<NodeId, Vec<CodeRefPreview>>,
    /// Workspace root path received from the backend `initialize` response.
    /// Used to strip the absolute prefix from code-ref file paths for display.
    workspace_root: Option<String>,
    /// Set of (node_id, ref_index) pairs that are currently expanded (show full code body).
    expanded_code_refs: std::collections::HashSet<(NodeId, usize)>,
    /// Current editing/selection mode for the spec tree.
    editor_mode: EditorMode,
    /// Which metadata item (if any) is currently being edited inline.
    editing_metadata: Option<MetadataEditTarget>,
    /// Set of spec_refs whose nodes recently changed (for fade-in animation).
    /// Cleared after a short delay.
    recently_changed: std::collections::HashSet<String>,
    /// Input for the bottom message bar (steer/queue messages to the active root agent).
    message_bar_input: Entity<InputState>,
    /// Input for the launch-agent dialog (task description).
    launch_dialog_input: Entity<InputState>,
    /// Scroll handle for the agent detail side panel.
    detail_scroll_handle: ScrollHandle,
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
        let notification_client = client.clone();

        let markdown_input = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Markdown...")
                .multi_line(true)
                .auto_grow(1, 20)
                .soft_wrap(true)
        });

        let message_bar_input = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Steer agent... (Enter to send)")
                .multi_line(false)
        });

        let launch_dialog_input = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Describe what you want the agent to do…")
                .multi_line(false)
        });

        cx.spawn(async move |this, cx| {
            let tree_result = async {
                let init = client_for_bootstrap.initialize(None).await?;
                let tree = client_for_bootstrap.get_tree_detailed().await?;
                Ok::<_, anyhow::Error>((init.workspace, tree))
            }
            .await;

            this.update(cx, |shell, cx| {
                match tree_result {
                    Ok((workspace, tree_response)) => {
                        shell.workspace_root = workspace;
                        let backend_nodes: Vec<BackendNode> = tree_response
                            .nodes
                            .into_iter()
                            .map(|n| BackendNode {
                                spec_ref: n.spec_ref,
                                depth: n.depth,
                                markdown: n.markdown,
                                status: n.status,
                                collapsed: n.collapsed,
                                code_refs: n.code_refs,
                                verification: n.verification,
                                depends_on: n.depends_on,
                                related_to: n.related_to,
                            })
                            .collect();
                        shell.state.hydrate_from_backend(backend_nodes);
                        shell.mark_flat_tree_dirty();
                        shell.client = Some(client);

                        // Collect nodes that have code_refs so we can fetch them eagerly.
                        let nodes_with_refs: Vec<(NodeId, String)> = shell
                            .state
                            .nodes
                            .iter()
                            .filter(|n| !n.code_refs.is_empty())
                            .map(|n| (n.id, n.spec_ref.clone()))
                            .collect();

                        if !nodes_with_refs.is_empty() {
                            let client_ref = shell.client.clone().unwrap();
                            cx.spawn(async move |this, cx| {
                                let mut results: Vec<(NodeId, Vec<CodeRefPreview>)> = Vec::new();
                                for (node_id, spec_ref) in nodes_with_refs {
                                    if let Ok(resp) = client_ref.get_node_code_refs(&spec_ref, None).await {
                                        results.push((node_id, resp.refs));
                                    }
                                }
                                this.update(cx, |shell, cx| {
                                    for (node_id, previews) in results {
                                        shell.code_ref_previews.insert(node_id, previews);
                                    }
                                    cx.notify();
                                })
                            })
                            .detach();
                        }
                    }
                    Err(e) => {
                        shell.state.backend_state = BackendState::Error(e.to_string());
                    }
                }
                cx.notify();
            })
        })
        .detach();

        // Start background task: listen for server-initiated notifications and
        // apply incremental patches to the tree without a full re-fetch.
        cx.spawn(async move |this, cx| {
            let mut notifications = notification_client.subscribe_notifications();
            loop {
                match notifications.recv().await {
                    Ok(notif) => {
                        let _ = this.update(cx, |shell, cx| {
                            shell.apply_server_notification(notif, cx);
                        });
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                        eprintln!("[taui] notification channel lagged, skipped {n} messages");
                        // Continue — we'll get the next one
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                        // Sender dropped — client is gone, exit
                        break;
                    }
                }
            }
            Ok::<_, anyhow::Error>(())
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
            tree_scroll_handle: ScrollHandle::new(),
            cached_markdown_style: None,
            cached_flat_tree: Vec::new(),
            flat_tree_dirty: true,
            cached_root_body: None,
            code_ref_previews: std::collections::HashMap::new(),
            workspace_root: None,
            expanded_code_refs: std::collections::HashSet::new(),
            editor_mode: EditorMode::Normal,
            editing_metadata: None,
            recently_changed: std::collections::HashSet::new(),
            message_bar_input: message_bar_input.clone(),
            launch_dialog_input: launch_dialog_input.clone(),
            detail_scroll_handle: ScrollHandle::new(),
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

        // Message bar: Enter triggers steer action.
        let msg_bar_sub = cx.subscribe_in(
            &message_bar_input,
            window,
            |this, _state, event, window, cx| {
                if let InputEvent::PressEnter { secondary: false } = event {
                    this.handle_message_bar_enter(window, cx);
                }
            },
        );
        shell._subscriptions.push(msg_bar_sub);

        // Launch dialog: Enter confirms launch.
        let launch_sub = cx.subscribe_in(
            &launch_dialog_input,
            window,
            |this, _state, event, window, cx| {
                if let InputEvent::PressEnter { secondary: false } = event {
                    this.confirm_launch_dialog(window, cx);
                }
            },
        );
        shell._subscriptions.push(launch_sub);

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

    /// Return a reference to the cached flat tree, rebuilding it if the dirty flag is set.
    /// No allocation occurs on cache-hit frames.
    fn get_flat_tree(&mut self) -> &Vec<FlatNode> {
        if self.flat_tree_dirty {
            #[cfg(debug_assertions)]
            let t0 = std::time::Instant::now();

            self.cached_flat_tree = self.state.flattened_tree_nodes();
            self.flat_tree_dirty = false;

            #[cfg(debug_assertions)]
            eprintln!(
                "[perf] flatten: {} nodes in {:?}",
                self.cached_flat_tree.len(),
                t0.elapsed()
            );
        }
        &self.cached_flat_tree
    }

    fn mark_flat_tree_dirty(&mut self) {
        self.flat_tree_dirty = true;
        self.cached_root_body = None;
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
            #[cfg(debug_assertions)]
            let t0 = std::time::Instant::now();

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

            #[cfg(debug_assertions)]
            eprintln!("[perf] structural action round-trip: {:?}", t0.elapsed());

            // Tree refresh is driven by the spec/treeChanged notification that the
            // backend emits after every structural mutation — no explicit re-fetch needed.
            this.update(&mut *cx, |shell, cx| {
                if let Err(e) = rpc_result {
                    shell.state.backend_state = BackendState::Error(e.to_string());
                    cx.notify();
                }
                Ok::<_, anyhow::Error>(())
            })
        })
        .detach();
    }

    fn auto_save_markdown(&mut self, cx: &mut Context<Self>) {
        // If editing a metadata item, save that instead of node markdown.
        if let Some(target) = self.editing_metadata.clone() {
            self.auto_save_metadata(target, cx);
            return;
        }

        let Some(node_id) = self.editing_node_id else {
            return;
        };
        let new_markdown = self.markdown_input.read(cx).value().to_string();

        if new_markdown != self.saved_markdown {
            let markdown = new_markdown.clone();
            let old_markdown = self.saved_markdown.clone();

            self.state.nodes[node_id].markdown = markdown.clone();
            self.saved_markdown = new_markdown;

            if let Some(client) = self.client.clone() {
                let spec_ref = self.state.nodes[node_id].spec_ref.clone();
                let is_locked = self.state.locked_branches.contains(&spec_ref);

                cx.spawn(async move |this, cx| {
                    let patch = serde_json::json!({
                        "markdown": markdown
                    });
                    let result = client.update_node(&spec_ref, patch).await;

                    // If the node is inside a locked branch, also send ui/nodeEdited
                    // so the backend can inject it as a steer message to the root agent.
                    if is_locked {
                        let _ = client.ui_node_edited(&spec_ref, &old_markdown, &markdown).await;
                    }

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

    /// Parse the edited raw `{{key: value}}` string and write back to local state.
    fn auto_save_metadata(&mut self, target: MetadataEditTarget, cx: &mut Context<Self>) {
        let raw = self.markdown_input.read(cx).value().to_string();
        if raw == self.saved_markdown {
            return;
        }
        self.saved_markdown = raw.clone();

        // Strip the `{{...}}` wrapper and split into key / value.
        let inner = raw
            .trim()
            .strip_prefix("{{")
            .and_then(|s| s.strip_suffix("}}"))
            .unwrap_or(raw.trim());
        let (key, value) = inner.split_once(':').map(|(k, v)| (k.trim(), v.trim())).unwrap_or(("", inner));

        match target {
            MetadataEditTarget::Verification { node_id } => {
                if node_id < self.state.nodes.len() {
                    if value.is_empty() && key.is_empty() {
                        self.state.nodes[node_id].verification = None;
                    } else {
                        self.state.nodes[node_id].verification = Some(value.to_string());
                    }
                }
            }
            MetadataEditTarget::DependsOn { node_id, index } => {
                if node_id < self.state.nodes.len() {
                    let deps = &mut self.state.nodes[node_id].depends_on;
                    if index < deps.len() {
                        deps[index] = value.to_string();
                    }
                }
            }
            MetadataEditTarget::RelatedTo { node_id, index } => {
                if node_id < self.state.nodes.len() {
                    let rels = &mut self.state.nodes[node_id].related_to;
                    if index < rels.len() {
                        rels[index] = value.to_string();
                    }
                }
            }
            MetadataEditTarget::CodeRef { node_id, ref_index } => {
                if node_id < self.state.nodes.len() {
                    let refs = &mut self.state.nodes[node_id].code_refs;
                    if ref_index < refs.len() {
                        // Strip backtick wrapping if present: `{{code_ref: `path`}}`
                        let stripped = value.trim_matches('`');
                        refs[ref_index] = stripped.to_string();
                    }
                }
                // Return to raw display mode (the header click will be gone, raw mode stays until re-toggled)
            }
        }
        cx.notify();
    }

    /// Begin inline editing of a metadata item.
    /// Loads the raw `{{key: value}}` string into `markdown_input` and sets `editing_metadata`.
    fn select_metadata_item(
        &mut self,
        target: MetadataEditTarget,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // Save any in-progress edits first.
        self.save_current_edits(cx);

        let raw: String = match &target {
            MetadataEditTarget::Verification { node_id } => {
                let v = self.state.nodes.get(*node_id)
                    .and_then(|n| n.verification.as_deref())
                    .unwrap_or("");
                format!("{{{{verification: {}}}}}", v)
            }
            MetadataEditTarget::DependsOn { node_id, index } => {
                let v = self.state.nodes.get(*node_id)
                    .and_then(|n| n.depends_on.get(*index).map(|s| s.as_str()))
                    .unwrap_or("");
                format!("{{{{depends_on: {}}}}}", v)
            }
            MetadataEditTarget::RelatedTo { node_id, index } => {
                let v = self.state.nodes.get(*node_id)
                    .and_then(|n| n.related_to.get(*index).map(|s| s.as_str()))
                    .unwrap_or("");
                format!("{{{{related_to: {}}}}}", v)
            }
            MetadataEditTarget::CodeRef { node_id, ref_index } => {
                let v = self.state.nodes.get(*node_id)
                    .and_then(|n| n.code_refs.get(*ref_index).map(|s| s.as_str()))
                    .unwrap_or("");
                format!("{{{{code_ref: `{}`}}}}", v)
            }
        };

        self.saved_markdown = raw.clone();
        self.editing_metadata = Some(target);
        // Clear node-level editing so render_row doesn't show a node input.
        self.editing_node_id = None;
        self.editor_mode = EditorMode::Editing;

        self.markdown_input.update(cx, |state, cx| {
            state.set_value(&raw, window, cx);
            state.focus(window, cx);
        });
        cx.notify();
    }

    fn sync_editing_markdown_preview(&mut self, cx: &mut Context<Self>) {
        // When editing metadata, there's no live markdown preview to sync.
        if self.editing_metadata.is_some() {
            return;
        }
        let Some(node_id) = self.editing_node_id else {
            return;
        };
        let Some(node) = self.state.nodes.get_mut(node_id) else {
            return;
        };
        let new_markdown = self.markdown_input.read(cx).value().to_string();
        if node.markdown != new_markdown {
            node.markdown = new_markdown.clone();
            // Update the cached flat tree entry for this node in-place — avoids full rebuild.
            if let Some(flat_node) = self.cached_flat_tree.iter_mut().find(|n| n.id == node_id) {
                flat_node.markdown = new_markdown;
            }
            cx.notify();
        }
    }

    fn select_node(&mut self, node_id: NodeId, window: &mut Window, cx: &mut Context<Self>) {
        self.save_current_edits(cx);

        // Update selection in cached flat tree in-place so we don't need a full rebuild.
        let prev_selected = self.state.selected_node;
        self.state.set_selected(node_id);
        self.editing_node_id = Some(node_id);
        self.editing_metadata = None;
        self.editor_mode = EditorMode::Editing;

        // Flip selected / selection_highlighted flags without a full rebuild.
        // selection_highlighted must be recalculated for the entire subtree when
        // selection changes, so do a full rebuild here.
        self.mark_flat_tree_dirty();
        let _ = self.get_flat_tree(); // warm cache immediately

        // Restore selected flag in-place (get_flat_tree uses state.selected_node).
        let _ = prev_selected; // used for the comment context above

        let node = &self.state.nodes[node_id];
        let markdown = node.markdown.clone();

        self.saved_markdown = markdown.clone();

        self.markdown_input.update(cx, |state, cx| {
            state.set_value(&markdown, window, cx);
        });

        cx.notify();
    }

    /// Enter selection mode on a node without activating the text cursor.
    fn select_node_no_edit(&mut self, node_id: NodeId, cx: &mut Context<Self>) {
        self.save_current_edits(cx);
        self.state.set_selected(node_id);
        self.editing_node_id = Some(node_id);
        self.editing_metadata = None;
        self.editor_mode = EditorMode::Selection;
        self.mark_flat_tree_dirty();
        cx.notify();
    }

    fn is_input_focused(&self, window: &Window, cx: &App) -> bool {
        let handle = self.markdown_input.read(cx).focus_handle(cx);
        handle.is_focused(window)
    }

    // -------------------------------------------------------------------------
    // Cursor / position helpers
    // -------------------------------------------------------------------------

    /// Convert a `(line, character)` cursor position to a byte offset within `text`.
    fn pos_to_byte_offset(text: &str, line: u32, character: u32) -> usize {
        let mut byte_offset = 0;
        for (li, l) in text.split('\n').enumerate() {
            if li as u32 == line {
                // character is a char (codepoint) count, not a byte offset.
                let char_off = character as usize;
                byte_offset += l.char_indices()
                    .nth(char_off)
                    .map(|(b, _)| b)
                    .unwrap_or(l.len());
                break;
            }
            byte_offset += l.len() + 1; // +1 for the '\n'
        }
        byte_offset
    }

    /// Given a byte offset in `text`, return the `(line, char_on_line)` position.
    fn byte_offset_to_pos(text: &str, byte_offset: usize) -> gpui_component::input::Position {
        let byte_offset = byte_offset.min(text.len());
        let prefix = &text[..byte_offset];
        let line = prefix.matches('\n').count() as u32;
        let last_newline = prefix.rfind('\n').map(|p| p + 1).unwrap_or(0);
        let character = prefix[last_newline..].chars().count() as u32;
        gpui_component::input::Position::new(line, character)
    }

    /// Move cursor to `byte_offset` within the current `markdown_input`.
    fn set_cursor_at_byte_offset(&mut self, byte_offset: usize, window: &mut Window, cx: &mut Context<Self>) {
        let text = self.markdown_input.read(cx).value().to_string();
        let pos = Self::byte_offset_to_pos(&text, byte_offset);
        self.markdown_input.update(cx, |state, cx| {
            state.set_cursor_position(pos, window, cx);
        });
    }

    /// Move to the adjacent visible node (delta=-1 for previous, +1 for next) in
    /// editing mode, placing the cursor at the start (next) or end (prev) of that node.
    fn move_editing_to_adjacent(
        &mut self,
        delta: isize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let flat = self.state.flattened_nodes();
        let current_id = match self.state.selected_node {
            Some(id) => id,
            None => return,
        };
        let Some(current_idx) = flat.iter().position(|n| n.id == current_id) else {
            return;
        };

        let target_idx = if delta < 0 {
            if current_idx == 0 { return; }
            current_idx - 1
        } else {
            let next = current_idx + 1;
            if next >= flat.len() { return; }
            next
        };

        let target_id = flat[target_idx].id;

        // Save current, switch node.
        self.save_current_edits(cx);
        self.state.set_selected(target_id);
        self.editing_node_id = Some(target_id);
        self.editor_mode = EditorMode::Editing;
        self.mark_flat_tree_dirty();

        let markdown = self.state.nodes[target_id].markdown.clone();
        self.saved_markdown = markdown.clone();

        // Place cursor at the appropriate end.
        let cursor_byte = if delta < 0 { markdown.len() } else { 0 };
        let cursor_pos = Self::byte_offset_to_pos(&markdown, cursor_byte);

        self.markdown_input.update(cx, |state, cx| {
            state.set_value(&markdown, window, cx);
            state.set_cursor_position(cursor_pos, window, cx);
            state.focus(window, cx);
        });
        cx.notify();
    }

    // -------------------------------------------------------------------------
    // Action handlers (capture phase — fire before Input widget sees actions)
    // -------------------------------------------------------------------------

    /// Handle the Enter / Shift+Enter action intercepted via `capture_action`.
    ///
    /// The Input widget registers `KeyBinding::new("enter", Enter { secondary: false })` and
    /// `KeyBinding::new("secondary-enter", Enter { secondary: true })` under the "Input" key
    /// context. Its `enter()` action handler inserts a newline for multi-line mode and never
    /// calls `cx.propagate()`, so our `capture_key_down` never fires for these keys. Instead we
    /// register a `capture_action::<InputEnter>` on the root div so we intercept the action
    /// during the capture phase (parent before child), before the Input bubble handler runs.
    ///
    /// `secondary = true` → Shift+Enter (insert literal `\n` within the node).
    /// `secondary = false` → Enter (split the node at cursor, or enter editing in Selection mode).
    fn handle_enter_action(
        &mut self,
        secondary: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let input_focused = self.is_input_focused(window, cx);

        if input_focused {
            if secondary {
                // ── Shift+Enter: insert literal newline within node ───────────
                let text = self.markdown_input.read(cx).value().to_string();
                let (byte_off, cur_line) = {
                    let input = self.markdown_input.read(cx);
                    let p = input.cursor_position();
                    (Self::pos_to_byte_offset(&text, p.line, p.character), p.line)
                };
                let mut new_text = String::with_capacity(text.len() + 1);
                new_text.push_str(&text[..byte_off]);
                new_text.push('\n');
                new_text.push_str(&text[byte_off..]);
                let new_line = cur_line + 1;
                self.markdown_input.update(cx, |state, cx| {
                    state.set_value(&new_text, window, cx);
                    state.set_cursor_position(
                        gpui_component::input::Position::new(new_line, 0),
                        window,
                        cx,
                    );
                });
                cx.notify();
                // Do NOT call cx.propagate() — event consumed here.
            } else {
                // ── Enter: split block at cursor ─────────────────────────────
                let (cursor_line, cursor_char) = {
                    let input = self.markdown_input.read(cx);
                    let p = input.cursor_position();
                    (p.line, p.character)
                };
                let text = self.markdown_input.read(cx).value().to_string();
                let byte_off = Self::pos_to_byte_offset(&text, cursor_line, cursor_char);

                // Flush current text into state before the split.
                if let Some(nid) = self.editing_node_id {
                    self.state.nodes[nid].markdown = text.clone();
                }

                // Capture fst info BEFORE split changes selected_node.
                let fst_id = self.state.selected_node;
                let fst_spec_ref = fst_id
                    .map(|id| self.state.nodes[id].spec_ref.clone())
                    .unwrap_or_default();
                let fst_markdown = text[..byte_off.min(text.len())].to_string();

                if let Some(new_id) = self.state.split_selected_at(byte_off) {
                    self.mark_flat_tree_dirty();

                    let snd_markdown = self.state.nodes[new_id].markdown.clone();
                    self.editing_node_id = Some(new_id);
                    self.editor_mode = EditorMode::Editing;
                    self.saved_markdown = snd_markdown.clone();

                    self.markdown_input.update(cx, |state, cx| {
                        state.set_value(&snd_markdown, window, cx);
                        state.set_cursor_position(
                            gpui_component::input::Position::new(0, 0),
                            window,
                            cx,
                        );
                        state.focus(window, cx);
                    });

                    self.sync_split_to_backend(fst_spec_ref, fst_markdown, snd_markdown, cx);
                    cx.notify();
                }
                // Do NOT call cx.propagate() — always consumed.
            }
        } else {
            // ── Selection / Normal mode ───────────────────────────────────────
            if !secondary && self.editor_mode == EditorMode::Selection {
                if let Some(selected) = self.state.selected_node {
                    self.select_node(selected, window, cx);
                    self.markdown_input.update(cx, |state, cx| {
                        state.focus(window, cx);
                    });
                    // consumed — do NOT propagate
                    return;
                }
            }
            // Nothing to do — propagate so other handlers can react.
            cx.propagate();
        }
    }

    /// Handle Tab (indent) / Shift+Tab (outdent) intercepted via `capture_action`.
    ///
    /// The Input registers `IndentInline` / `OutdentInline` actions for Tab / Shift+Tab under the
    /// "Input" key context. Even though AutoGrow mode makes `is_indentable()` false (so the Input
    /// handler calls `cx.propagate()`), we intercept at the capture phase to be reliable across
    /// all Input configurations.
    ///
    /// `is_outdent = false` → Tab (IndentNode), `is_outdent = true` → Shift+Tab (OutdentNode).
    fn handle_tab_action(
        &mut self,
        is_outdent: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.save_current_edits(cx);
        if is_outdent {
            self.apply_structural(UiAction::OutdentNode, cx);
        } else {
            self.apply_structural(UiAction::IndentNode, cx);
        }
        match self.editor_mode {
            EditorMode::Editing => {
                if let Some(selected) = self.state.selected_node {
                    // Preserve cursor position — select_node resets it via set_value.
                    let (cur_line, cur_char) = {
                        let input = self.markdown_input.read(cx);
                        let p = input.cursor_position();
                        (p.line, p.character)
                    };
                    self.select_node(selected, window, cx);
                    self.markdown_input.update(cx, |state, cx| {
                        state.set_cursor_position(
                            gpui_component::input::Position::new(cur_line, cur_char),
                            window,
                            cx,
                        );
                        state.focus(window, cx);
                    });
                }
            }
            EditorMode::Selection => {
                if let Some(selected) = self.state.selected_node {
                    self.select_node_no_edit(selected, cx);
                }
            }
            EditorMode::Normal => {}
        }
        // Do NOT call cx.propagate() — always consumed.
    }

    // -------------------------------------------------------------------------
    // Main key handler
    // -------------------------------------------------------------------------

    /// Handle a key-down event. Returns `true` if the event was consumed (caller
    /// should call `cx.stop_propagation()`), `false` if it should pass through.
    fn handle_key_down(
        &mut self,
        event: &KeyDownEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> bool {
        let keystroke = &event.keystroke;
        let key = keystroke.key.to_string().to_ascii_lowercase();
        let shift = keystroke.modifiers.shift;
        let ctrl  = keystroke.modifiers.control;
        let alt   = keystroke.modifiers.alt;
        let meta  = keystroke.modifiers.platform;

        // NOTE: Enter, Shift+Enter, Tab, and Shift+Tab are handled via capture_action
        // (see handle_enter_action / handle_tab_action). They are NOT handled here because
        // the Input widget consumes those keystrokes through its action system before
        // capture_key_down fires.

        let input_focused = self.is_input_focused(window, cx);

        // ── Keys handled only while the text cursor is active (Editing mode) ─
        if input_focused {
            // If the launch dialog is open and focused, Escape closes it.
            if self.state.launch_dialog_node.is_some() {
                if key == "escape" {
                    self.close_launch_dialog(cx);
                    return true;
                }
                // All other keys in the dialog input pass through to it.
                return false;
            }

            match key.as_str() {
                // ── Escape: Editing → Selection ──────────────────────────────
                "escape" => {
                    self.save_current_edits(cx);
                    self.focus_handle.focus(window);
                    self.editor_mode = EditorMode::Selection;
                    cx.notify();
                    return true;
                }

                // ── Backspace at position (0,0): merge into previous node ────
                "backspace" if !shift && !ctrl && !alt && !meta => {
                    let (cursor_line, cursor_char, cursor_at_start) = {
                        let input = self.markdown_input.read(cx);
                        let p = input.cursor_position();
                        let at_start = input.cursor() == 0 && p.line == 0 && p.character == 0;
                        (p.line, p.character, at_start)
                    };

                    if cursor_line == 0 && cursor_char == 0 && cursor_at_start {
                        let current_text = self.markdown_input.read(cx).value().to_string();
                        if let Some(nid) = self.editing_node_id {
                            self.state.nodes[nid].markdown = current_text;
                        }

                        if let Some((target_id, join_offset)) =
                            self.state.merge_selected_into_previous()
                        {
                            self.mark_flat_tree_dirty();
                            self.editing_node_id = Some(target_id);
                            self.editor_mode = EditorMode::Editing;

                            let merged_text = self.state.nodes[target_id].markdown.clone();
                            self.saved_markdown = merged_text.clone();

                            self.markdown_input.update(cx, |state, cx| {
                                state.set_value(&merged_text, window, cx);
                                state.focus(window, cx);
                            });
                            self.set_cursor_at_byte_offset(join_offset, window, cx);

                            self.sync_merge_to_backend(cx);
                            cx.notify();
                        }
                        return true; // consume — don't let input handle it
                    }
                    return false; // cursor not at start — pass through
                }

                // ── Delete at end of text: merge next node in ─────────────────
                "delete" if !shift && !ctrl && !alt && !meta => {
                    let at_end = {
                        let input = self.markdown_input.read(cx);
                        let text = input.value();
                        let byte_cursor = input.cursor();
                        byte_cursor >= text.len()
                    };

                    if at_end {
                        let current_text = self.markdown_input.read(cx).value().to_string();
                        if let Some(nid) = self.editing_node_id {
                            self.state.nodes[nid].markdown = current_text;
                        }

                        if let Some(join_offset) = self.state.merge_next_into_selected() {
                            self.mark_flat_tree_dirty();
                            let selected_id = self.state.selected_node.unwrap();
                            self.editing_node_id = Some(selected_id);
                            self.editor_mode = EditorMode::Editing;

                            let merged_text = self.state.nodes[selected_id].markdown.clone();
                            self.saved_markdown = merged_text.clone();

                            self.markdown_input.update(cx, |state, cx| {
                                state.set_value(&merged_text, window, cx);
                                state.focus(window, cx);
                            });
                            self.set_cursor_at_byte_offset(join_offset, window, cx);

                            self.sync_merge_to_backend(cx);
                            cx.notify();
                            return true;
                        }
                    }
                    return false; // not at end, or no next node — pass through
                }

                // ── Up arrow at first line: jump to previous node ─────────────
                "arrowup" | "up" if !shift && !ctrl && !alt && !meta => {
                    let at_first_line = {
                        let input = self.markdown_input.read(cx);
                        input.cursor_position().line == 0
                    };
                    if at_first_line {
                        self.move_editing_to_adjacent(-1, window, cx);
                        return true;
                    }
                    return false; // pass through to input
                }

                // ── Down arrow at last line: jump to next node ───────────────
                "arrowdown" | "down" if !shift && !ctrl && !alt && !meta => {
                    let at_last_line = {
                        let input = self.markdown_input.read(cx);
                        let text = input.value().to_string();
                        let total_lines = text.lines().count().max(1) as u32;
                        let cursor_line = input.cursor_position().line;
                        cursor_line >= total_lines - 1
                    };
                    if at_last_line {
                        self.move_editing_to_adjacent(1, window, cx);
                        return true;
                    }
                    return false; // pass through to input
                }

                // ── Left arrow at position 0,0: jump to end of previous node ─
                "arrowleft" | "left" if !shift && !ctrl && !alt && !meta => {
                    let at_start = {
                        let input = self.markdown_input.read(cx);
                        let p = input.cursor_position();
                        p.line == 0 && p.character == 0
                    };
                    if at_start {
                        self.move_editing_to_adjacent(-1, window, cx);
                        return true;
                    }
                    return false;
                }

                // ── Right arrow at end of text: jump to start of next node ───
                "arrowright" | "right" if !shift && !ctrl && !alt && !meta => {
                    let at_end = {
                        let input = self.markdown_input.read(cx);
                        let byte_cursor = input.cursor();
                        byte_cursor >= input.value().len()
                    };
                    if at_end {
                        self.move_editing_to_adjacent(1, window, cx);
                        return true;
                    }
                    return false;
                }

                _ => {}
            }
            // All other keys in editing mode: pass through to the input widget.
            return false;
        }

        // ── Keys handled in Selection / Normal mode (input NOT focused) ───────
        match key.as_str() {
            // ── Escape: Selection → Normal ───────────────────────────────────
            "escape" => {
                if self.editor_mode == EditorMode::Selection {
                    self.state.selected_node = None;
                    self.state.selected_spec_ref = None;
                    self.editing_node_id = None;
                    self.editor_mode = EditorMode::Normal;
                    self.mark_flat_tree_dirty();
                    cx.notify();
                    return true;
                }
            }

            // NOTE: Enter in Selection mode handled by handle_enter_action (capture_action).

            // ── Up / Down in selection mode: move highlight ───────────────────
            "arrowup" | "up" => {
                self.apply(UiAction::SelectPrevious, cx);
                if let Some(selected) = self.state.selected_node {
                    self.select_node_no_edit(selected, cx);
                }
                return true;
            }
            "arrowdown" | "down" => {
                self.apply(UiAction::SelectNext, cx);
                if let Some(selected) = self.state.selected_node {
                    self.select_node_no_edit(selected, cx);
                }
                return true;
            }

            _ => {
                // Delegate to keybindings map for remaining actions.
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
                                self.select_node_no_edit(selected, cx);
                            }
                        }
                        UiAction::ToggleCollapse => {
                            self.apply(action, cx);
                            if let Some(client) = self.client.clone() {
                                if let Some(selected) = self.state.selected_node {
                                    let collapsed = self.state.nodes[selected].collapsed;
                                    let spec_ref = self.state.nodes[selected].spec_ref.clone();

                                    cx.spawn(async move |this, cx| {
                                        let result = client.set_node_collapsed(&spec_ref, collapsed).await;
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
                    return true;
                }
            }
        }
        false // not consumed
    }

    // ── Backend sync helpers for split / merge ────────────────────────────────

    /// After a split, sync both halves to the backend.
    ///
    /// `fst_spec_ref` – spec_ref of the first-half node (already updated locally).
    /// `fst_markdown`  – the truncated text for the first-half node.
    /// `snd_markdown`  – the text for the newly-created second-half node.
    fn sync_split_to_backend(
        &mut self,
        fst_spec_ref: String,
        fst_markdown: String,
        snd_markdown: String,
        cx: &mut Context<Self>,
    ) {
        let Some(client) = self.client.clone() else { return };

        cx.spawn(async move |_this, _cx| {
            // 1. Persist the truncated first-half content.
            let _ = client.update_node(
                &fst_spec_ref,
                serde_json::json!({ "markdown": fst_markdown }),
            ).await;

            // 2. Create an empty sibling after fst on the backend.
            let snd_result = client.create_sibling_node(&fst_spec_ref).await;

            // 3. If sibling creation succeeded, update its content.
            if let Ok(snd_response) = snd_result {
                let snd_spec_ref = snd_response.node.spec_ref;
                let _ = client.update_node(
                    &snd_spec_ref,
                    serde_json::json!({ "markdown": snd_markdown }),
                ).await;
            }

            // Tree reconciliation is driven by spec/nodeCreated and spec/treeChanged
            // notifications emitted by the backend — no explicit re-fetch needed here.
            Ok::<_, anyhow::Error>(())
        })
        .detach();
    }

    /// After a merge, sync the merged node to the backend and re-fetch.
    fn sync_merge_to_backend(&mut self, cx: &mut Context<Self>) {
        let Some(client) = self.client.clone() else { return };
        let Some(selected) = self.state.selected_node else { return };
        let spec_ref = self.state.nodes[selected].spec_ref.clone();
        let markdown = self.state.nodes[selected].markdown.clone();

        cx.spawn(async move |_this, _cx| {
            let _ = client.update_node(
                &spec_ref,
                serde_json::json!({ "markdown": markdown }),
            ).await;
            // Tree reconciliation is driven by spec/nodeChanged and spec/treeChanged
            // notifications emitted by the backend — no explicit re-fetch needed here.
            Ok::<_, anyhow::Error>(())
        })
        .detach();
    }

    // ── Server notification handler ───────────────────────────────────────────

    /// Parse a `TreeNode` from a notification `params` dict (under `"node"` key).
    fn parse_notification_node(params: &serde_json::Value) -> Option<BackendNode> {
        let node = params.get("node")?;
        Some(BackendNode {
            spec_ref: node.get("spec_ref")?.as_str()?.to_string(),
            depth: node.get("depth")?.as_u64()? as usize,
            markdown: node.get("markdown")?.as_str()?.to_string(),
            status: node.get("status").and_then(|v| v.as_str()).map(|s| s.to_string()),
            collapsed: node.get("collapsed").and_then(|v| v.as_bool()).unwrap_or(false),
            code_refs: node.get("code_refs")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default(),
            verification: node.get("verification").and_then(|v| v.as_str()).map(|s| s.to_string()),
            depends_on: node.get("depends_on")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default(),
            related_to: node.get("related_to")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default(),
        })
    }

    /// Apply a server-initiated notification to the local state incrementally.
    fn apply_server_notification(&mut self, notif: ServerNotification, cx: &mut Context<Self>) {
        match notif.method.as_str() {
            "spec/nodeChanged" => {
                if let Some(backend_node) = Self::parse_notification_node(&notif.params) {
                    let spec_ref = backend_node.spec_ref.clone();
                    // Handle spec_ref rename: the node's anchor may have changed.
                    // The params may include a `previous_spec_ref` at root level.
                    let prev_ref = notif.params
                        .get("previous_spec_ref")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                    if let Some(old_ref) = prev_ref {
                        if old_ref != spec_ref {
                            self.state.rename_node_spec_ref(&old_ref, &spec_ref);
                        }
                    }
                    if self.state.patch_node_from_backend(&backend_node).is_some() {
                        self.recently_changed.insert(spec_ref.clone());
                        self.mark_flat_tree_dirty();
                        // Schedule clearing the animation flag.
                        let spec_ref_for_clear = spec_ref.clone();
                        cx.spawn(async move |this, cx| {
                            tokio::time::sleep(std::time::Duration::from_millis(600)).await;
                            let _ = this.update(cx, |shell, cx| {
                                shell.recently_changed.remove(&spec_ref_for_clear);
                                cx.notify();
                            });
                            Ok::<_, anyhow::Error>(())
                        })
                        .detach();
                        cx.notify();
                    }
                }
            }
            "spec/nodeCreated" => {
                if let Some(backend_node) = Self::parse_notification_node(&notif.params) {
                    let spec_ref = backend_node.spec_ref.clone();
                    // For a new node we need its parent to insert it correctly.
                    // The backend sends depth — we do a full re-fetch for structure safety.
                    // Mark as recently changed for animation.
                    self.recently_changed.insert(spec_ref.clone());
                    let spec_ref_for_clear = spec_ref.clone();
                    cx.spawn(async move |this, cx| {
                        tokio::time::sleep(std::time::Duration::from_millis(600)).await;
                        let _ = this.update(cx, |shell, cx| {
                            shell.recently_changed.remove(&spec_ref_for_clear);
                            cx.notify();
                        });
                        Ok::<_, anyhow::Error>(())
                    })
                    .detach();
                    // Re-fetch the full tree to incorporate the new node.
                    if let Some(client) = self.client.clone() {
                        cx.spawn(async move |this, cx| {
                            if let Ok(tree) = client.get_tree_detailed().await {
                                this.update(&mut *cx, |shell, cx| {
                                    let backend_nodes = Self::tree_response_to_backend_nodes(tree.nodes);
                                    shell.state.hydrate_from_backend(backend_nodes);
                                    shell.mark_flat_tree_dirty();
                                    cx.notify();
                                })
                            } else {
                                Ok(())
                            }
                        })
                        .detach();
                    }
                }
            }
            "spec/nodeDeleted" => {
                // Re-fetch the full tree to reflect the deletion.
                if let Some(client) = self.client.clone() {
                    cx.spawn(async move |this, cx| {
                        if let Ok(tree) = client.get_tree_detailed().await {
                            this.update(&mut *cx, |shell, cx| {
                                let backend_nodes = Self::tree_response_to_backend_nodes(tree.nodes);
                                shell.state.hydrate_from_backend(backend_nodes);
                                shell.mark_flat_tree_dirty();
                                cx.notify();
                            })
                        } else {
                            Ok(())
                        }
                    })
                    .detach();
                }
            }
            "spec/treeChanged" => {
                // Structural change (reparenting, indentation, outdentation, etc.)
                // Re-fetch the full tree.
                if let Some(client) = self.client.clone() {
                    cx.spawn(async move |this, cx| {
                        if let Ok(tree) = client.get_tree_detailed().await {
                            this.update(&mut *cx, |shell, cx| {
                                let backend_nodes = Self::tree_response_to_backend_nodes(tree.nodes);
                                shell.state.hydrate_from_backend(backend_nodes);
                                shell.mark_flat_tree_dirty();
                                cx.notify();
                            })
                        } else {
                            Ok(())
                        }
                    })
                    .detach();
                }
            }
            _ => {
                // Agent notifications
                match notif.method.as_str() {
                    "agent/stateChanged" => {
                        if let (Some(agent_id), Some(state_str), Some(spec_ref)) = (
                            notif.params.get("agent_id").and_then(|v| v.as_str()),
                            notif.params.get("state").and_then(|v| v.as_str()),
                            notif.params.get("spec_ref").and_then(|v| v.as_str()),
                        ) {
                            let state = AgentState::from_str(state_str);
                            let tier_str = notif.params.get("tier").and_then(|v| v.as_str()).unwrap_or("mid");
                            let tier = AgentTier::from_str(tier_str);
                            let agent_id = agent_id.to_string();
                            let spec_ref = spec_ref.to_string();

                            // Push detail event if detail panel is open for this agent.
                            if self.state.detail_agent_id.as_deref() == Some(&agent_id) {
                                self.state.push_detail_event(
                                    &agent_id,
                                    AgentDetailEvent::StateChange { state: AgentState::from_str(state_str) },
                                );
                            }

                            self.state.upsert_agent(agent_id, spec_ref, state, tier);
                            self.mark_flat_tree_dirty();
                            cx.notify();
                        }
                    }
                    "agent/toolBrief" => {
                        if let (Some(agent_id), Some(tool_name)) = (
                            notif.params.get("agent_id").and_then(|v| v.as_str()),
                            notif.params.get("tool_name").and_then(|v| v.as_str()),
                        ) {
                            let agent_id = agent_id.to_string();
                            let tool_name = tool_name.to_string();
                            self.state.set_agent_tool_brief(&agent_id, tool_name.clone());
                            self.mark_flat_tree_dirty();

                            // Auto-clear tool brief after 4 seconds.
                            let agent_id_clear = agent_id.clone();
                            cx.spawn(async move |this, cx| {
                                tokio::time::sleep(std::time::Duration::from_secs(4)).await;
                                let _ = this.update(cx, |shell, cx| {
                                    shell.state.clear_agent_tool_brief(&agent_id_clear);
                                    shell.mark_flat_tree_dirty();
                                    cx.notify();
                                });
                                Ok::<_, anyhow::Error>(())
                            })
                            .detach();

                            cx.notify();
                        }
                    }
                    "agent/lockChanged" => {
                        if let (Some(spec_ref), Some(locked)) = (
                            notif.params.get("spec_ref").and_then(|v| v.as_str()),
                            notif.params.get("locked").and_then(|v| v.as_bool()),
                        ) {
                            if locked {
                                self.state.locked_branches.insert(spec_ref.to_string());
                            } else {
                                self.state.locked_branches.remove(spec_ref);
                            }
                            self.mark_flat_tree_dirty();
                            cx.notify();
                        }
                    }
                    "agent/questionAsked" => {
                        if let (Some(agent_id), Some(question_node)) = (
                            notif.params.get("agent_id").and_then(|v| v.as_str()),
                            notif.params.get("question_node"),
                        ) {
                            let question_node_ref = question_node
                                .get("spec_ref")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string();
                            let question = question_node
                                .get("question")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string();
                            let options: Vec<String> = question_node
                                .get("options")
                                .and_then(|v| v.as_array())
                                .map(|arr| {
                                    arr.iter()
                                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                                        .collect()
                                })
                                .unwrap_or_default();

                            self.state.add_question(PendingQuestion {
                                agent_id: agent_id.to_string(),
                                question_node_ref,
                                question,
                                options,
                            });
                            self.mark_flat_tree_dirty();
                            cx.notify();
                        }
                    }
                    // Detail stream events — only relevant when subscribed (panel is open).
                    "agent/message" => {
                        if let Some(agent_id) = notif.params.get("agent_id").and_then(|v| v.as_str()) {
                            if self.state.detail_agent_id.as_deref() == Some(agent_id) {
                                let message = notif.params.get("message").cloned().unwrap_or_default();
                                let role = message.get("role").and_then(|v| v.as_str()).unwrap_or("assistant").to_string();
                                let content = message.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                self.state.push_detail_event(
                                    agent_id,
                                    AgentDetailEvent::Message { role, content },
                                );
                                cx.notify();
                            }
                        }
                    }
                    "agent/toolCall" => {
                        if let Some(agent_id) = notif.params.get("agent_id").and_then(|v| v.as_str()) {
                            if self.state.detail_agent_id.as_deref() == Some(agent_id) {
                                let call_id = notif.params.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let tool_name = notif.params.get("tool_name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let arguments = notif.params.get("arguments").cloned().unwrap_or(serde_json::Value::Null);
                                self.state.push_detail_event(
                                    agent_id,
                                    AgentDetailEvent::ToolCall { call_id, tool_name, arguments },
                                );
                                cx.notify();
                            }
                        }
                    }
                    "agent/toolResult" => {
                        if let Some(agent_id) = notif.params.get("agent_id").and_then(|v| v.as_str()) {
                            if self.state.detail_agent_id.as_deref() == Some(agent_id) {
                                let call_id = notif.params.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let output = notif.params.get("output").and_then(|v| v.as_str()).map(|s| s.to_string());
                                let error = notif.params.get("error").and_then(|v| v.as_str()).map(|s| s.to_string());
                                let duration_ms = notif.params.get("duration_ms").and_then(|v| v.as_u64());
                                self.state.push_detail_event(
                                    agent_id,
                                    AgentDetailEvent::ToolResult { call_id, output, error, duration_ms },
                                );
                                cx.notify();
                            }
                        }
                    }
                    "agent/token" => {
                        if let Some(agent_id) = notif.params.get("agent_id").and_then(|v| v.as_str()) {
                            if self.state.detail_agent_id.as_deref() == Some(agent_id) {
                                let text = notif.params.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                self.state.push_detail_event(
                                    agent_id,
                                    AgentDetailEvent::Token { text },
                                );
                                cx.notify();
                            }
                        }
                    }
                    _ => {
                        // Unknown notification — ignore.
                    }
                }
            }
        }
    }

    fn tree_response_to_backend_nodes(
        nodes: Vec<crate::services::backend_client::TreeNode>,
    ) -> Vec<BackendNode> {
        nodes
            .into_iter()
            .map(|n| BackendNode {
                spec_ref: n.spec_ref,
                depth: n.depth,
                markdown: n.markdown,
                status: n.status,
                collapsed: n.collapsed,
                code_refs: n.code_refs,
                verification: n.verification,
                depends_on: n.depends_on,
                related_to: n.related_to,
            })
            .collect()
    }

    // -------------------------------------------------------------------------
    // Message bar helpers
    // -------------------------------------------------------------------------

    /// Called when the user presses Enter in the message bar input.
    /// Steers the currently active root agent with the typed message.
    fn handle_message_bar_enter(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let text = self.message_bar_input.read(cx).value().to_string();
        let text = text.trim().to_string();
        if text.is_empty() {
            return;
        }
        let Some(agent) = self.state.active_agents().next() else {
            return;
        };
        let agent_id = agent.agent_id.clone();
        let Some(client) = self.client.clone() else {
            return;
        };
        // Clear input immediately (synchronously — we have window here).
        self.message_bar_input.update(cx, |state, cx| {
            state.set_value("", window, cx);
        });
        cx.spawn(async move |_this, _cx| {
            let _ = client.agent_steer(&agent_id, &text).await;
            Ok::<_, anyhow::Error>(())
        })
        .detach();
    }

    /// Open the agent detail panel for a given agent id.
    /// Subscribes to the agent's event stream and loads backlog.
    fn open_detail_panel(&mut self, agent_id: String, cx: &mut Context<Self>) {
        // If already open for this agent, close it (toggle).
        if self.state.detail_agent_id.as_deref() == Some(&agent_id) {
            self.close_detail_panel(cx);
            return;
        }
        // Close any previously open panel.
        self.close_detail_panel(cx);

        self.state.detail_agent_id = Some(agent_id.clone());
        self.state.detail_events.entry(agent_id.clone()).or_default();

        if let Some(client) = self.client.clone() {
            let agent_id_sub = agent_id.clone();
            cx.spawn(async move |this, cx| {
                match client.agent_subscribe(&agent_id_sub).await {
                    Ok(backlog) => {
                        let _ = this.update(cx, |shell, cx| {
                            // Only apply if the panel is still open for this agent.
                            if shell.state.detail_agent_id.as_deref() == Some(&agent_id_sub) {
                                let events = shell
                                    .state
                                    .detail_events
                                    .entry(agent_id_sub.clone())
                                    .or_default();
                                for item in backlog {
                                    // Map backlog items to AgentDetailEvents.
                                    if let Some(ev) = Self::parse_backlog_item(&item) {
                                        events.push(ev);
                                    }
                                }
                                cx.notify();
                            }
                        });
                    }
                    Err(e) => {
                        eprintln!("[taui] agent_subscribe failed: {e}");
                    }
                }
                Ok::<_, anyhow::Error>(())
            })
            .detach();
        }
        cx.notify();
    }

    /// Close the detail panel and unsubscribe from the agent's stream.
    fn close_detail_panel(&mut self, cx: &mut Context<Self>) {
        if let Some(agent_id) = self.state.detail_agent_id.take() {
            if let Some(client) = self.client.clone() {
                let agent_id_unsub = agent_id.clone();
                cx.spawn(async move |_this, _cx| {
                    let _ = client.agent_unsubscribe(&agent_id_unsub).await;
                    Ok::<_, anyhow::Error>(())
                })
                .detach();
            }
        }
        cx.notify();
    }

    /// Convert a backlog JSON item (from `agent_subscribe`) into an `AgentDetailEvent`.
    fn parse_backlog_item(item: &serde_json::Value) -> Option<AgentDetailEvent> {
        let kind = item.get("type").and_then(|v| v.as_str())?;
        match kind {
            "message" => {
                let role = item.get("role").and_then(|v| v.as_str()).unwrap_or("assistant").to_string();
                let content = item.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string();
                Some(AgentDetailEvent::Message { role, content })
            }
            "tool_call" => {
                let call_id = item.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let tool_name = item.get("tool_name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let arguments = item.get("arguments").cloned().unwrap_or(serde_json::Value::Null);
                Some(AgentDetailEvent::ToolCall { call_id, tool_name, arguments })
            }
            "tool_result" => {
                let call_id = item.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let output = item.get("output").and_then(|v| v.as_str()).map(|s| s.to_string());
                let error = item.get("error").and_then(|v| v.as_str()).map(|s| s.to_string());
                let duration_ms = item.get("duration_ms").and_then(|v| v.as_u64());
                Some(AgentDetailEvent::ToolResult { call_id, output, error, duration_ms })
            }
            "state_change" => {
                let state_str = item.get("state").and_then(|v| v.as_str()).unwrap_or("unknown");
                Some(AgentDetailEvent::StateChange { state: AgentState::from_str(state_str) })
            }
            _ => None,
        }
    }

    // -------------------------------------------------------------------------
    // Launch dialog: open/close/confirm + render
    // -------------------------------------------------------------------------

    /// Open the "launch agent" dialog for a node. Clears the input and focuses it.
    fn open_launch_dialog(&mut self, spec_ref: String, window: &mut Window, cx: &mut Context<Self>) {
        self.state.launch_dialog_node = Some(spec_ref);
        self.state.launch_dialog_tier = AgentTier::Mid;
        self.launch_dialog_input.update(cx, |state, cx| {
            state.set_value("", window, cx);
            state.focus(window, cx);
        });
        cx.notify();
    }

    /// Close the launch dialog without launching.
    fn close_launch_dialog(&mut self, cx: &mut Context<Self>) {
        self.state.launch_dialog_node = None;
        cx.notify();
    }

    /// Confirm the launch dialog: read the task text, call agent/launch, close the dialog.
    fn confirm_launch_dialog(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let task = self.launch_dialog_input.read(cx).value().trim().to_string();
        if task.is_empty() {
            return;
        }
        let Some(spec_ref) = self.state.launch_dialog_node.clone() else {
            return;
        };
        let tier = self.state.launch_dialog_tier.label().to_string();

        // Close the dialog immediately.
        self.state.launch_dialog_node = None;
        self.launch_dialog_input.update(cx, |state, cx| {
            state.set_value("", window, cx);
        });

        if let Some(client) = self.client.clone() {
            cx.spawn(async move |_this, _cx| {
                let _ = client.agent_launch(&spec_ref, &task, &tier).await;
                Ok::<_, anyhow::Error>(())
            })
            .detach();
        }
        cx.notify();
    }

    /// Render the floating "launch agent" dialog as a top-level overlay.
    fn render_launch_dialog(&mut self, spec_ref: &str, _window: &mut Window, cx: &mut Context<Self>) -> gpui::AnyElement {
        let colors = self.theme.styles.colors.clone();

        // Node title (first line of markdown).
        let node_title: String = self
            .state
            .spec_ref_index
            .get(spec_ref)
            .and_then(|&id| self.state.nodes.get(id))
            .map(|n| {
                n.markdown
                    .lines()
                    .next()
                    .unwrap_or("")
                    .trim()
                    .to_string()
            })
            .unwrap_or_else(|| spec_ref.to_string());

        let current_tier = self.state.launch_dialog_tier.clone();

        // Tier pill buttons.
        let tiers = [
            ("Senior", AgentTier::Senior),
            ("Mid", AgentTier::Mid),
            ("Junior", AgentTier::Junior),
        ];

        let mut tier_row = div().flex().flex_row().gap_1();
        for (label, tier) in tiers {
            let is_selected = current_tier == tier;
            let tier_clone = tier.clone();
            tier_row = tier_row.child(
                div()
                    .px_2()
                    .py(px(3.0))
                    .rounded(px(4.0))
                    .border_1()
                    .text_size(px(11.0))
                    .cursor_pointer()
                    .when(is_selected, |this| {
                        this.border_color(rgb(0x3b82f6))
                            .text_color(rgb(0x3b82f6))
                            .bg(rgba(0x3b82f614))
                    })
                    .when(!is_selected, |this| {
                        this.border_color(rgb(colors.border))
                            .text_color(rgb(colors.text_muted))
                    })
                    .child(label)
                    .on_mouse_down(
                        MouseButton::Left,
                        cx.listener(move |this, _ev, _window, cx| {
                            this.state.launch_dialog_tier = tier_clone.clone();
                            cx.notify();
                        }),
                    ),
            );
        }

        // Backdrop — clicking outside closes the dialog.
        let backdrop = div()
            .absolute()
            .inset_0()
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(|this, _ev, _window, cx| {
                    this.close_launch_dialog(cx);
                }),
            );

        // Dialog card.
        let launch_dialog_input = self.launch_dialog_input.clone();
        let card = div()
            .absolute()
            // Position: centred horizontally, ~30% from top.
            .inset_0()
            .flex()
            .items_start()
            .justify_center()
            .pt(px(120.0))
            // Stop clicks on the card from bubbling to the backdrop.
            .on_mouse_down(MouseButton::Left, |_ev, _window, cx| cx.stop_propagation())
            .child(
                div()
                    .w(px(380.0))
                    .rounded(px(8.0))
                    .border_1()
                    .border_color(rgb(0x3b82f6))
                    .bg(rgb(colors.element_background))
                    .shadow_lg()
                    .flex()
                    .flex_col()
                    .gap_2()
                    .p(px(14.0))
                    // Header
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .justify_between()
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .gap_1()
                                    .child(
                                        div()
                                            .w(px(6.0))
                                            .h(px(6.0))
                                            .rounded_full()
                                            .bg(rgb(0x3b82f6)),
                                    )
                                    .child(
                                        div()
                                            .text_size(px(12.0))
                                            .text_color(rgb(colors.text_muted))
                                            .child("Start agent on"),
                                    )
                                    .child(
                                        div()
                                            .text_size(px(12.0))
                                            .text_color(rgb(colors.text))
                                            .font_weight(FontWeight::SEMIBOLD)
                                            .child(node_title),
                                    ),
                            )
                            .child(
                                div()
                                    .text_size(px(11.0))
                                    .text_color(rgb(colors.text_muted))
                                    .cursor_pointer()
                                    .child("✕")
                                    .on_mouse_down(
                                        MouseButton::Left,
                                        cx.listener(|this, _ev, _window, cx| {
                                            this.close_launch_dialog(cx);
                                        }),
                                    ),
                            ),
                    )
                    // Task input
                    .child(
                        div()
                            .rounded(px(4.0))
                            .border_1()
                            .border_color(rgb(colors.border))
                            .bg(rgb(colors.background))
                            .px_2()
                            .py_1()
                            .child(
                                Input::new(&launch_dialog_input)
                                    .appearance(false)
                                    .bordered(false)
                                    .px(px(0.0))
                                    .py(px(0.0))
                                    .text_size(px(13.0)),
                            ),
                    )
                    // Tier selector + Launch button row
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .justify_between()
                            .child(tier_row)
                            .child(
                                div()
                                    .px_3()
                                    .py_1()
                                    .rounded(px(4.0))
                                    .bg(rgb(0x3b82f6))
                                    .text_size(px(12.0))
                                    .text_color(rgb(0xffffff))
                                    .cursor_pointer()
                                    .child("Launch")
                                    .on_mouse_down(
                                        MouseButton::Left,
                                        cx.listener(|this, _ev, window, cx| {
                                            this.confirm_launch_dialog(window, cx);
                                        }),
                                    ),
                            ),
                    ),
            );

        div()
            .absolute()
            .inset_0()
            .child(backdrop)
            .child(card)
            .into_any_element()
    }

    // -------------------------------------------------------------------------
    // Render: Message bar
    // -------------------------------------------------------------------------

    /// Bottom bar shown when any root agent is active.
    /// Contains: optional tool brief row, text input, steer/queue/stop buttons.
    fn render_message_bar(
        &mut self,
        agent_id: &str,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) -> gpui::AnyElement {
        let colors = self.theme.styles.colors.clone();
        let agent_id = agent_id.to_string();

        // Tool brief: agent name + tool name from active tool brief.
        let tool_brief: Option<String> = self
            .state
            .agents
            .get(&agent_id)
            .and_then(|a| a.tool_brief.clone());

        let client_steer = self.client.clone();
        let client_stop = self.client.clone();
        let client_queue = self.client.clone();
        let agent_id_steer = agent_id.clone();
        let agent_id_stop = agent_id.clone();
        let agent_id_queue = agent_id.clone();
        let msg_input = self.message_bar_input.clone();
        let msg_input_queue = self.message_bar_input.clone();

        let bar = div()
            .w_full()
            .border_t_1()
            .border_color(rgb(colors.border))
            .bg(rgb(colors.element_background))
            .flex()
            .flex_col()
            .px_3()
            .py_2()
            .gap_1()
            // Tool brief row
            .when_some(tool_brief, |this, brief| {
                this.child(
                    div()
                        .flex()
                        .items_center()
                        .gap_1()
                        .child(
                            div()
                                .w(px(6.0))
                                .h(px(6.0))
                                .rounded_full()
                                .bg(rgb(0x3b82f6)),
                        )
                        .child(
                            div()
                                .text_size(px(11.0))
                                .text_color(rgb(colors.text_muted))
                                .child(brief),
                        ),
                )
            })
            // Input + buttons row
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap_2()
                    // Text input
                    .child(
                        div()
                            .flex_1()
                            .rounded(px(4.0))
                            .border_1()
                            .border_color(rgb(colors.border))
                            .bg(rgb(colors.background))
                            .px_2()
                            .py_1()
                            .child(
                                Input::new(&self.message_bar_input)
                                    .appearance(false)
                                    .bordered(false)
                                    .px(px(0.0))
                                    .py(px(0.0))
                                    .text_size(px(13.0)),
                            ),
                    )
                    // Steer button
                    .child(
                        div()
                            .px_2()
                            .py_1()
                            .rounded(px(4.0))
                            .border_1()
                            .border_color(rgb(colors.border))
                            .text_size(px(12.0))
                            .text_color(rgb(colors.text))
                            .cursor_pointer()
                            .child("Steer")
                            .on_mouse_down(
                                MouseButton::Left,
                                cx.listener(move |_this, _ev, window, cx| {
                                    let text = msg_input.read(cx).value().to_string();
                                    let text = text.trim().to_string();
                                    if text.is_empty() { return; }
                                    // Clear input synchronously (window is available here).
                                    msg_input.update(cx, |state, cx| {
                                        state.set_value("", window, cx);
                                    });
                                    if let Some(client) = client_steer.clone() {
                                        let id = agent_id_steer.clone();
                                        cx.spawn(async move |_this2, _cx| {
                                            let _ = client.agent_steer(&id, &text).await;
                                            Ok::<_, anyhow::Error>(())
                                        }).detach();
                                    }
                                }),
                            ),
                    )
                    // Queue button
                    .child(
                        div()
                            .px_2()
                            .py_1()
                            .rounded(px(4.0))
                            .border_1()
                            .border_color(rgb(colors.border))
                            .text_size(px(12.0))
                            .text_color(rgb(colors.text))
                            .cursor_pointer()
                            .child("Queue")
                            .on_mouse_down(
                                MouseButton::Left,
                                cx.listener(move |_this, _ev, window, cx| {
                                    let text = msg_input_queue.read(cx).value().to_string();
                                    let text = text.trim().to_string();
                                    if text.is_empty() { return; }
                                    // Clear input synchronously.
                                    msg_input_queue.update(cx, |state, cx| {
                                        state.set_value("", window, cx);
                                    });
                                    if let Some(client) = client_queue.clone() {
                                        let id = agent_id_queue.clone();
                                        cx.spawn(async move |_this2, _cx| {
                                            let _ = client.agent_queue(&id, &text).await;
                                            Ok::<_, anyhow::Error>(())
                                        }).detach();
                                    }
                                }),
                            ),
                    )
                    // Stop button
                    .child(
                        div()
                            .px_2()
                            .py_1()
                            .rounded(px(4.0))
                            .border_1()
                            .border_color(rgb(0xf59e0b))
                            .text_size(px(12.0))
                            .text_color(rgb(0xf59e0b))
                            .cursor_pointer()
                            .child("⏹ Stop")
                            .on_mouse_down(
                                MouseButton::Left,
                                cx.listener(move |_this, _ev, _window, cx| {
                                    if let Some(client) = client_stop.clone() {
                                        let id = agent_id_stop.clone();
                                        cx.spawn(async move |_this2, _cx| {
                                            let _ = client.agent_stop(&id).await;
                                            Ok::<_, anyhow::Error>(())
                                        }).detach();
                                    }
                                }),
                            ),
                    ),
            );

        bar.into_any_element()
    }

    // -------------------------------------------------------------------------
    // Render: Agent detail side panel
    // -------------------------------------------------------------------------

    /// Right-side panel showing the agent's event stream.
    fn render_detail_panel(
        &mut self,
        agent_id: &str,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) -> gpui::AnyElement {
        let colors = self.theme.styles.colors.clone();
        let status_colors = self.theme.styles.status.clone();
        let agent_id = agent_id.to_string();

        // Agent info snapshot
        let (agent_state_label, agent_tier_label, agent_spec_ref) = self
            .state
            .agents
            .get(&agent_id)
            .map(|a| {
                let state_lbl = match &a.state {
                    AgentState::Idle => "idle",
                    AgentState::Running => "running",
                    AgentState::Thinking => "thinking",
                    AgentState::ToolExecution => "tool",
                    AgentState::AskingQuestion => "asking",
                    AgentState::WaitingForAnswer => "waiting",
                    AgentState::Stopping => "stopping",
                    AgentState::Done => "done",
                    AgentState::Unknown(_) => "unknown",
                };
                (state_lbl, a.tier.label(), a.spec_ref.clone())
            })
            .unwrap_or(("unknown", "mid", String::new()));

        // Collect detail events.
        let events: Vec<AgentDetailEvent> = self
            .state
            .detail_events
            .get(&agent_id)
            .cloned()
            .unwrap_or_default();

        let scroll_handle = self.detail_scroll_handle.clone();

        // Build event timeline elements.
        let mut event_els: Vec<gpui::AnyElement> = Vec::new();
        for event in &events {
            let el: gpui::AnyElement = match event {
                AgentDetailEvent::Message { role, content } => {
                    let is_user = role == "user";
                    let label_color = if is_user {
                        rgb(0x3b82f6u32)
                    } else {
                        rgb(colors.text_muted)
                    };
                    let role_label: SharedString = role.clone().into();
                    let content_text: SharedString = content.clone().into();
                    div()
                        .flex()
                        .flex_col()
                        .gap_px()
                        .py_1()
                        .child(
                            div()
                                .text_size(px(10.0))
                                .text_color(label_color)
                                .child(role_label),
                        )
                        .child(
                            div()
                                .text_size(px(12.0))
                                .text_color(rgb(colors.text))
                                .child(content_text),
                        )
                        .into_any_element()
                }
                AgentDetailEvent::ToolCall { tool_name, arguments, .. } => {
                    let tool: SharedString = format!("▶ {}", tool_name).into();
                    let args_str: SharedString = serde_json::to_string_pretty(arguments)
                        .unwrap_or_default()
                        .into();
                    div()
                        .flex()
                        .flex_col()
                        .gap_px()
                        .py_1()
                        .child(
                            div()
                                .text_size(px(11.0))
                                .text_color(rgb(0x3b82f6u32))
                                .child(tool),
                        )
                        .child(
                            div()
                                .text_size(px(10.0))
                                .text_color(rgb(colors.text_muted))
                                .font_family(CODE_FONT_FAMILY)
                                .child(args_str),
                        )
                        .into_any_element()
                }
                AgentDetailEvent::ToolResult { output, error, duration_ms, .. } => {
                    let result_text: SharedString = if let Some(err) = error {
                        format!("✗ {}", err).into()
                    } else {
                        let out = output.as_deref().unwrap_or("(no output)");
                        let truncated = if out.len() > 200 { &out[..200] } else { out };
                        format!("✓ {}", truncated).into()
                    };
                    let duration_text: Option<SharedString> =
                        duration_ms.map(|ms| format!("{}ms", ms).into());
                    let result_color = if error.is_some() {
                        rgb(status_colors.error)
                    } else {
                        rgb(0x22c55eu32)
                    };
                    div()
                        .flex()
                        .flex_col()
                        .gap_px()
                        .py_1()
                        .child(
                            div()
                                .text_size(px(11.0))
                                .text_color(result_color)
                                .child(result_text),
                        )
                        .when_some(duration_text, |this, dur| {
                            this.child(
                                div()
                                    .text_size(px(10.0))
                                    .text_color(rgb(colors.text_muted))
                                    .child(dur),
                            )
                        })
                        .into_any_element()
                }
                AgentDetailEvent::Token { text } => {
                    let t: SharedString = text.clone().into();
                    div()
                        .text_size(px(11.0))
                        .text_color(rgb(colors.text_muted))
                        .child(t)
                        .into_any_element()
                }
                AgentDetailEvent::StateChange { state } => {
                    let lbl: SharedString = format!(
                        "→ {}",
                        match state {
                            AgentState::Idle => "idle",
                            AgentState::Running => "running",
                            AgentState::Thinking => "thinking",
                            AgentState::ToolExecution => "tool execution",
                            AgentState::AskingQuestion => "asking question",
                            AgentState::WaitingForAnswer => "waiting for answer",
                            AgentState::Stopping => "stopping",
                            AgentState::Done => "done",
                            AgentState::Unknown(s) => s.as_str(),
                        }
                    ).into();
                    div()
                        .text_size(px(10.0))
                        .text_color(rgb(colors.text_muted))
                        .py_px()
                        .child(lbl)
                        .into_any_element()
                }
            };
            event_els.push(el);
        }

        let panel = div()
            .w(px(320.0))
            .h_full()
            .border_l_1()
            .border_color(rgb(colors.border))
            .bg(rgb(colors.element_background))
            .flex()
            .flex_col()
            // Header
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .px_3()
                    .py_2()
                    .border_b_1()
                    .border_color(rgb(colors.border))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .gap_px()
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .gap_1()
                                    .child(
                                        div()
                                            .w(px(8.0))
                                            .h(px(8.0))
                                            .rounded_full()
                                            .bg(rgb(0x3b82f6u32)),
                                    )
                                    .child(
                                        div()
                                            .text_size(px(13.0))
                                            .text_color(rgb(colors.text))
                                            .child(agent_state_label),
                                    )
                                    .child(
                                        div()
                                            .text_size(px(10.0))
                                            .text_color(rgb(colors.text_muted))
                                            .child(agent_tier_label),
                                    ),
                            )
                            .child(
                                div()
                                    .text_size(px(10.0))
                                    .text_color(rgb(colors.text_muted))
                                    .child(agent_spec_ref),
                            ),
                    )
                    // Close button
                    .child(
                        div()
                            .text_size(px(16.0))
                            .text_color(rgb(colors.text_muted))
                            .cursor_pointer()
                            .child("✕")
                            .on_mouse_down(
                                MouseButton::Left,
                                cx.listener(move |this, _ev, _window, cx| {
                                    this.close_detail_panel(cx);
                                }),
                            ),
                    ),
            )
            // Event timeline (scrollable)
            .child(
                div()
                    .id("detail-scroll")
                    .flex_1()
                    .overflow_y_scroll()
                    .track_scroll(&scroll_handle)
                    .px_3()
                    .py_2()
                    .flex()
                    .flex_col()
                    .gap_1()
                    .children(event_els)
                    .when(events.is_empty(), |this| {
                        this.child(
                            div()
                                .text_size(px(12.0))
                                .text_color(rgb(colors.text_muted))
                                .child("No events yet"),
                        )
                    }),
            );

        panel.into_any_element()
    }

    fn render_row(
        &mut self,
        row: &FlatNode,
        is_root: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> impl IntoElement {
        let node_id = row.id;
        let row_has_children = row.has_children;
        let colors = self.theme.styles.colors.clone();

        // Chevron for expand/collapse - hidden for root, rendered for other nodes with children
        let chevron: Option<gpui::AnyElement> =
            component_adapters::render_chevron(row.collapsed, row_has_children, is_root, node_id, cx);

        let group_id: SharedString = format!("node-row-{}", node_id).into();

        // spec_ref for this node — used by bullet click to open launch dialog or detail panel.
        let node_spec_ref = self.state.nodes[node_id].spec_ref.clone();
        // If there's an active agent on this node, bullet click opens the detail panel instead.
        let active_agent_id_for_bullet: Option<String> = self
            .state
            .agent_for_spec_ref(&node_spec_ref)
            .map(|a| a.agent_id.clone());

        // Bullet marker - always shown; grows on row hover; clickable to start/view agent convo.
        let bullet_spec_ref = node_spec_ref.clone();
        let bullet = div()
            .id(("bullet", node_id))
            .child("•")
            .text_color(rgb(0xc0c0c0))
            .text_size(px(22.0))
            .group_hover(group_id.clone(), |s| s.text_size(px(28.0)).text_color(rgb(0x909090)))
            .active(|s| s.text_color(rgb(0x606060)))
            .cursor_pointer()
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(move |this, _ev, window, cx| {
                    if let Some(ref agent_id) = active_agent_id_for_bullet {
                        // Agent already active on this node — open detail panel.
                        this.open_detail_panel(agent_id.clone(), cx);
                    } else {
                        // No agent — open the launch dialog for this node.
                        this.open_launch_dialog(bullet_spec_ref.clone(), window, cx);
                    }
                }),
            );

        let chevron_slot = {
            let inner = chevron.unwrap_or_else(|| div().w(px(24.0)).into_any_element());
            div()
                .invisible()
                .group_hover(group_id.clone(), |s| s.visible())
                .child(inner)
        };
        let left_controls = div()
            .flex()
            .h(px(f32::from(MARKDOWN_TEXT_SIZE) * MARKDOWN_LINE_HEIGHT))
            .items_center()
            .gap_1()
            .child(chevron_slot)
            .child(bullet);

        let is_active_editor = self.editor_mode == EditorMode::Editing
            && self.editing_node_id == Some(node_id);
        let is_empty = row.markdown.trim().is_empty();

        // --- Agent indicator (right side) ---
        // Colors: blue dot for active agent, amber dot for question pending.
        // Blue dot is clickable to open/close the detail panel.
        let agent_indicator: Option<gpui::AnyElement> = if row.has_question {
            Some(
                div()
                    .flex()
                    .items_center()
                    .gap_1()
                    .pt(px(4.0))
                    .child(
                        div()
                            .w(px(8.0))
                            .h(px(8.0))
                            .rounded_full()
                            .bg(rgb(0xf59e0b)), // amber — question pending
                    )
                    .into_any_element(),
            )
        } else if let Some(agent_id_for_dot) = row.agent_id.clone() {
            // Lookup tool brief for this agent.
            let tool_brief = self
                .state
                .agents
                .get(&agent_id_for_dot)
                .and_then(|a| a.tool_brief.clone());
            Some(
                div()
                    .flex()
                    .items_center()
                    .gap_1()
                    .pt(px(4.0))
                    .when_some(tool_brief, |this, brief| {
                        this.child(
                            div()
                                .text_size(px(10.0))
                                .text_color(rgb(colors.text_muted))
                                .max_w(px(120.0))
                                .overflow_hidden()
                                .child(brief),
                        )
                    })
                    .child(
                        div()
                            .w(px(8.0))
                            .h(px(8.0))
                            .rounded_full()
                            .bg(rgb(0x3b82f6)) // blue — agent active
                            .cursor_pointer()
                            .on_mouse_down(
                                MouseButton::Left,
                                cx.listener(move |this, _ev, _window, cx| {
                                    this.open_detail_panel(agent_id_for_dot.clone(), cx);
                                }),
                            ),
                    )
                    .into_any_element(),
            )
        } else {
            None
        };

        // Content area
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
        } else if is_empty {
            // Placeholder for empty nodes in view mode.
            div()
                .flex_1()
                .cursor_text()
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
                    div()
                        .text_color(rgb(colors.text_muted))
                        .text_size(MARKDOWN_TEXT_SIZE)
                        .line_height(relative(MARKDOWN_LINE_HEIGHT))
                        .child("Type something…"),
                )
        } else {
            let markdown_style = self.get_markdown_style();
            let heading = depth_to_heading_style(row.depth);
            let (title, body) = split_root_markdown(&row.markdown);
            let has_body = !body.trim().is_empty();
            let click_listener = cx.listener(move |this, _event: &MouseDownEvent, window, cx| {
                this.select_node(node_id, window, cx);
                this.markdown_input.update(cx, |state, cx| {
                    state.focus(window, cx);
                });
            });
            div()
                .flex_1()
                .cursor_text()
                .on_mouse_down(MouseButton::Left, click_listener)
                .child(
                    div()
                        .text_size(heading.font_size)
                        .font_weight(heading.font_weight)
                        .line_height(relative(MARKDOWN_LINE_HEIGHT))
                        .text_color(rgb(colors.text))
                        .child(title),
                )
                .when(has_body, |this| {
                    let body_view_id = ("node-markdown-body", node_id);
                    this.child(
                        TextView::markdown(body_view_id, body, window, cx)
                            .style(markdown_style)
                            .text_size(MARKDOWN_TEXT_SIZE)
                            .line_height(relative(MARKDOWN_LINE_HEIGHT))
                            .text_color(rgb(colors.text)),
                    )
                })
        };

        // Vertical padding scales down with depth: root(d=0)→10px, d=1→6px, d=2→4px, d≥3→2px
        let py = if is_root {
            px(10.0)
        } else {
            match row.depth {
                0 | 1 => px(6.0),
                2      => px(4.0),
                _      => px(2.0),
            }
        };
        let padding = (px(10.0), py);

        let is_locked = row.locked;

        let mut row_el = div()
            .w_full()
            .flex()
            .flex_col()
            .px(padding.0)
            .py(padding.1)
            .group(group_id)
            // Editing mode: left border indicator on this node's row
            .when(is_active_editor, |this| {
                this.border_l_2().border_color(rgb(colors.border))
            })
            // Locked branch: subtle amber/orange left border
            .when(is_locked && !is_active_editor, |this| {
                this.border_l_2().border_color(rgb(0xf59e0b))
            });

        let inner_row = div()
            .flex()
            .items_start()
            .gap_2()
            .child(left_controls.pt(px(0.0)))
            .child(content_area);

        let inner_row = if let Some(indicator) = agent_indicator {
            inner_row.child(indicator)
        } else {
            inner_row
        };

        row_el = row_el.child(inner_row);

        // --- Question overlay ---
        // Rendered as an inline card below the row content when there's a pending question.
        if row.has_question {
            let node_spec_ref = self.state.nodes[node_id].spec_ref.clone();
            if let Some(question) = self
                .state
                .pending_questions
                .iter()
                .find(|q| q.question_node_ref == node_spec_ref)
                .cloned()
            {
                let question_ref = question.question_node_ref.clone();
                let question_text: SharedString = question.question.clone().into();
                let options = question.options.clone();

                let mut question_card = div()
                    .mt(px(6.0))
                    .ml(px(48.0)) // align with content area
                    .p(px(10.0))
                    .rounded(px(6.0))
                    .border_1()
                    .border_color(rgb(0xf59e0b))
                    .bg(rgb(0x1c1a12))
                    .flex()
                    .flex_col()
                    .gap_2()
                    // Question text
                    .child(
                        div()
                            .text_size(px(12.0))
                            .text_color(rgb(0xfbbf24))
                            .child("Agent question"),
                    )
                    .child(
                        div()
                            .text_size(px(13.0))
                            .text_color(rgb(colors.text))
                            .child(question_text),
                    );

                // Option buttons (if any)
                if !options.is_empty() {
                    let mut opts_row = div().flex().flex_row().flex_wrap().gap_1();
                    for opt in options {
                        let opt_text: SharedString = opt.clone().into();
                        let question_ref_for_opt = question_ref.clone();
                        let client_opt = self.client.clone();
                        opts_row = opts_row.child(
                            div()
                                .px(px(8.0))
                                .py(px(3.0))
                                .rounded(px(4.0))
                                .border_1()
                                .border_color(rgb(0xf59e0b))
                                .text_size(px(12.0))
                                .text_color(rgb(0xfbbf24))
                                .cursor_pointer()
                                .on_mouse_down(
                                    MouseButton::Left,
                                    cx.listener({
                                        let answer = opt.clone();
                                        move |_this, _event, _window, cx| {
                                            let qref = question_ref_for_opt.clone();
                                            let ans = answer.clone();
                                            if let Some(client) = client_opt.clone() {
                                                cx.spawn(async move |this2, cx| {
                                                    let _ = client.agent_answer_question(&qref, &ans).await;
                                                    let _ = this2.update(cx, |shell, cx| {
                                                        shell.state.remove_question(&qref);
                                                        shell.mark_flat_tree_dirty();
                                                        cx.notify();
                                                    });
                                                    Ok::<_, anyhow::Error>(())
                                                })
                                                .detach();
                                            }
                                        }
                                    }),
                                )
                                .child(opt_text),
                        );
                    }
                    question_card = question_card.child(opts_row);
                }

                // Dismiss button
                let dismiss_ref = question_ref.clone();
                question_card = question_card.child(
                    div()
                        .text_size(px(11.0))
                        .text_color(rgb(colors.text_muted))
                        .cursor_pointer()
                        .child("Dismiss")
                        .on_mouse_down(
                            MouseButton::Left,
                            cx.listener(move |this, _event, _window, cx| {
                                this.state.remove_question(&dismiss_ref);
                                this.mark_flat_tree_dirty();
                                cx.notify();
                            }),
                        ),
                );

                row_el = row_el.child(question_card);
            }
        }

        row_el
    }

    /// Render a node and its visible children as a recursive nested container.
    /// The node's own row is rendered at the top, and its children (if any and
    /// not collapsed) are wrapped in a shared container with a left-border indent
    /// indicator. The selection blue background is applied to the outermost
    /// container so it spans the node and all its descendants as one block.
    ///
    /// `ancestor_is_selected` is true when a parent (or ancestor) node is the
    /// currently selected node. This propagates the blue highlight downward only,
    /// so siblings and ancestors of the selected node are never highlighted.
    fn render_node(
        &mut self,
        node_id: NodeId,
        is_root: bool,
        ancestor_is_selected: bool,
        depth: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> gpui::AnyElement {
        let colors = self.theme.styles.colors.clone();

        // Build a FlatNode snapshot for render_row (avoids restructuring that function).
        let node = &self.state.nodes[node_id];
        let is_selected = self.state.selected_node == Some(node_id);
        let spec_ref = node.spec_ref.clone();
        let agent_id = self.state.agents.values().find_map(|a| {
            if a.spec_ref == spec_ref && a.state.is_active() {
                Some(a.agent_id.clone())
            } else {
                None
            }
        });
        let locked = self.state.locked_branches.contains(&spec_ref);
        let has_question = self.state.pending_questions.iter().any(|q| q.question_node_ref == spec_ref);

        let flat = FlatNode {
            id: node_id,
            depth,
            markdown: if is_root {
                // Root: use cached body (title shown in titlebar)
                if self.cached_root_body.as_ref().map(|(rid, _)| *rid) != Some(node_id)
                    || self.cached_root_body.is_none()
                {
                    let (_, body) = split_root_markdown(&node.markdown);
                    self.cached_root_body = Some((node_id, body));
                }
                self.cached_root_body
                    .as_ref()
                    .map(|(_, b)| b.clone())
                    .unwrap_or_default()
            } else {
                node.markdown.clone()
            },
            selected: is_selected,
            selection_highlighted: is_selected,
            collapsed: node.collapsed,
            has_children: !node.children.is_empty(),
            code_refs: node.code_refs.clone(),
            verification: node.verification.clone(),
            depends_on: node.depends_on.clone(),
            related_to: node.related_to.clone(),
            agent_id,
            locked,
            has_question,
        };

        let is_collapsed = node.collapsed;
        let children_ids: Vec<NodeId> = node.children.clone();

        // Determine whether this node should receive the blue selection background.
        // Only the selected node itself and its descendants (children/grandchildren/…)
        // are highlighted — ancestors and siblings are NOT highlighted.
        let subtree_highlighted = self.editor_mode == EditorMode::Selection
            && (is_selected || ancestor_is_selected);

        // Selection highlight color
        let selection_bg = if self.is_dark_theme() {
            rgba(0x3B82F614u32)
        } else {
            rgba(0x3B82F60Du32)
        };

        // Fade-in highlight for recently changed nodes (green tint, 600 ms).
        let node_spec_ref = self.state.nodes[node_id].spec_ref.clone();
        let is_recently_changed = self.recently_changed.contains(&node_spec_ref);
        let recently_changed_bg = if self.is_dark_theme() {
            rgba(0x22C55E18u32) // green-500 at ~10% opacity
        } else {
            rgba(0x22C55E0Du32) // green-500 at ~5% opacity
        };

        // The node's own content row.
        let this_row = self.render_row(&flat, is_root, window, cx);

        // Metadata children: code_refs + verification + depends_on + related_to,
        // rendered as child nodes with bullet + indentation (same indent as spec children).
        let meta_children_el: Option<gpui::AnyElement> = {
            let colors = self.theme.styles.colors.clone();
            let code_refs = flat.code_refs.clone();
            let verification = flat.verification.clone();
            let depends_on = flat.depends_on.clone();
            let related_to = flat.related_to.clone();

            let previews_for_node = self.code_ref_previews.get(&node_id).cloned();

        // Build code_ref child elements
        let mut meta_els: Vec<gpui::AnyElement> = Vec::new();

        for (ref_index, raw_ref) in code_refs.iter().enumerate() {
            let is_expanded = self.expanded_code_refs.contains(&(node_id, ref_index));
            let is_editing_this = self.editing_metadata
                == Some(MetadataEditTarget::CodeRef { node_id, ref_index });

            let preview = previews_for_node
                .as_ref()
                .and_then(|ps| ps.get(ref_index));

            let input_ref = if is_editing_this {
                Some(&self.markdown_input)
            } else {
                None
            };

            let child_el = component_adapters::render_code_ref_child(
                raw_ref,
                preview,
                node_id,
                ref_index,
                is_expanded,
                is_editing_this,
                input_ref,
                self.workspace_root.as_deref(),
                &colors,
                cx,
            );
            meta_els.push(child_el);
        }

        // Verification child
        if let Some(v) = &verification {
            let text: SharedString = format!("{{{{verification: {}}}}}", v).into();
            let is_editing_this = self.editing_metadata
                == Some(MetadataEditTarget::Verification { node_id });
            let input_ref = if is_editing_this {
                Some(&self.markdown_input)
            } else {
                None
            };
            // element_key: kind=1, index=0
            let element_key: u64 = ((node_id as u64) << 20) | (1u64 << 16);
            meta_els.push(
                component_adapters::render_metadata_child(
                    text,
                    &colors,
                    is_editing_this,
                    input_ref,
                    element_key,
                    move |this, window, cx| {
                        this.select_metadata_item(
                            MetadataEditTarget::Verification { node_id },
                            window,
                            cx,
                        );
                    },
                    cx,
                )
                .into_any_element(),
            );
        }

        // depends_on children (one per entry)
        for (dep_index, dep) in depends_on.iter().enumerate() {
            let text: SharedString = format!("{{{{depends_on: {}}}}}", dep).into();
            let is_editing_this = self.editing_metadata
                == Some(MetadataEditTarget::DependsOn { node_id, index: dep_index });
            let input_ref = if is_editing_this {
                Some(&self.markdown_input)
            } else {
                None
            };
            // element_key: kind=2
            let element_key: u64 = ((node_id as u64) << 20) | (2u64 << 16) | (dep_index as u64);
            meta_els.push(
                component_adapters::render_metadata_child(
                    text,
                    &colors,
                    is_editing_this,
                    input_ref,
                    element_key,
                    move |this, window, cx| {
                        this.select_metadata_item(
                            MetadataEditTarget::DependsOn { node_id, index: dep_index },
                            window,
                            cx,
                        );
                    },
                    cx,
                )
                .into_any_element(),
            );
        }

        // related_to children (one per entry)
        for (rel_index, rel) in related_to.iter().enumerate() {
            let text: SharedString = format!("{{{{related_to: {}}}}}", rel).into();
            let is_editing_this = self.editing_metadata
                == Some(MetadataEditTarget::RelatedTo { node_id, index: rel_index });
            let input_ref = if is_editing_this {
                Some(&self.markdown_input)
            } else {
                None
            };
            // element_key: kind=3
            let element_key: u64 = ((node_id as u64) << 20) | (3u64 << 16) | (rel_index as u64);
            meta_els.push(
                component_adapters::render_metadata_child(
                    text,
                    &colors,
                    is_editing_this,
                    input_ref,
                    element_key,
                    move |this, window, cx| {
                        this.select_metadata_item(
                            MetadataEditTarget::RelatedTo { node_id, index: rel_index },
                            window,
                            cx,
                        );
                    },
                    cx,
                )
                .into_any_element(),
            );
        }

            if meta_els.is_empty() {
                None
            } else {
                Some(
                    div()
                        .pl(INDENT_PER_LEVEL)
                        .ml(px(25.0))
                        .border_l_1()
                        .border_color(rgb(colors.border_variant))
                        .flex()
                        .flex_col()
                        .children(meta_els)
                        .into_any_element(),
                )
            }
        };

        // Children container: indent + left border, only if not collapsed.
        // Level 0 (root's direct children) are rendered flat — no indent or border.
        let children_el: Option<gpui::AnyElement> = if !is_collapsed && !children_ids.is_empty() {
            // Propagate highlight downward: children of the selected node (or
            // a node whose ancestor is selected) should also be highlighted.
            let child_ancestor_selected = is_selected || ancestor_is_selected;
            let child_depth = depth + 1;
            let child_els: Vec<gpui::AnyElement> = children_ids
                .iter()
                .map(|&cid| self.render_node(cid, false, child_ancestor_selected, child_depth, window, cx))
                .collect();

            if is_root {
                // Level 0: no indentation or left-border for root's direct children.
                Some(
                    div()
                        .flex()
                        .flex_col()
                        .children(child_els)
                        .into_any_element(),
                )
            } else {
                Some(
                    div()
                        .pl(INDENT_PER_LEVEL)
                        .ml(px(25.0)) // align left border under the bullet
                        .border_l_1()
                        .border_color(rgb(colors.border_variant))
                        .flex()
                        .flex_col()
                        .children(child_els)
                        .into_any_element(),
                )
            }
        } else {
            None
        };

        // Outer container: wraps this node's row + children.
        // Blue background goes here so it covers the whole subtree as one block.
        div()
            .w_full()
            .max_w(MAX_CONTENT_WIDTH)
            .flex()
            .flex_col()
            .when(subtree_highlighted, |this| this.bg(selection_bg))
            .when(is_recently_changed && !subtree_highlighted, |this| this.bg(recently_changed_bg))
            .child(this_row)
            .children(meta_children_el)
            .children(children_el)
            .into_any_element()
    }
}

impl Render for AppShell {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        #[cfg(debug_assertions)]
        let _render_t0 = std::time::Instant::now();

        self.sync_window_title(window);

        // The flat tree cache is still used for keyboard navigation (up/down/adjacent moves).
        // It is not iterated for rendering anymore; rendering uses render_node() recursively.
        let _ = self.get_flat_tree();
        let colors = self.theme.styles.colors.clone();
        let status = self.theme.styles.status.clone();

        let root = div()
            .size_full()
            .flex()
            .flex_col()
            .bg(rgb(colors.background))
            .text_color(rgb(colors.text))
            .font_family(BODY_FONT_FAMILY)
            .track_focus(&self.focus_handle);

        let root = root.capture_key_down(cx.listener(|this, event, window, cx| {
            if this.handle_key_down(event, window, cx) {
                cx.stop_propagation();
            }
        }));

        // Intercept Enter / Tab / Shift-Tab **before** the Input's bubble-phase on_action
        // handlers run (which don't propagate), so we can implement our own tree-level logic.
        let root = root
            .capture_action::<InputEnter>(cx.listener(|this, action: &InputEnter, window, cx| {
                this.handle_enter_action(action.secondary, window, cx);
            }))
            .capture_action::<IndentInline>(cx.listener(|this, _: &IndentInline, window, cx| {
                this.handle_tab_action(false, window, cx);
            }))
            .capture_action::<OutdentInline>(cx.listener(
                |this, _: &OutdentInline, window, cx| {
                    this.handle_tab_action(true, window, cx);
                },
            ));

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

        // Warm the root body cache.
        if let Some(id) = root_id {
            if self.cached_root_body.as_ref().map(|(rid, _)| *rid) != Some(id) {
                let (_, body) = split_root_markdown(&self.state.nodes[id].markdown);
                self.cached_root_body = Some((id, body));
            }
        }

        let titlebar = TitleBar::new()
            .child(
                div()
                    .ml_2()
                    .flex()
                    .items_center()
                    .h_full()
                    .child(
                        div()
                            .text_base()
                            .child(root_title),
                    ),
            );

        let scroll_handle = self.tree_scroll_handle.clone();

        // Render the root node (its body) then recursively render all children
        // as nested containers.
        let root_node_el: Option<gpui::AnyElement> = root_id.map(|id| {
            self.render_node(id, true, false, 0, window, cx)
        });

        // Non-root top-level nodes (rare — secondary spec files, etc.)
        let extra_root_ids: Vec<NodeId> = self
            .state
            .root_nodes
            .iter()
            .copied()
            .filter(|&id| Some(id) != root_id)
            .collect();
        let extra_root_els: Vec<gpui::AnyElement> = extra_root_ids
            .into_iter()
            .map(|id| self.render_node(id, false, false, 0, window, cx))
            .collect();

        // Determine if any root agent is active — used for message bar and detail panel.
        let active_agent_id: Option<String> = self
            .state
            .active_agents()
            .next()
            .map(|a| a.agent_id.clone());

        // Detail panel (open for specific agent).
        let detail_agent_id: Option<String> = self.state.detail_agent_id.clone();
        let detail_panel_el: Option<gpui::AnyElement> = detail_agent_id
            .as_deref()
            .map(|id| self.render_detail_panel(id, window, cx));

        // Message bar (shown when any agent is active).
        let message_bar_el: Option<gpui::AnyElement> = active_agent_id
            .as_deref()
            .map(|id| self.render_message_bar(id, window, cx));

        // Launch dialog overlay (shown when bullet is clicked on a node with no active agent).
        let launch_dialog_spec_ref: Option<String> = self.state.launch_dialog_node.clone();
        let launch_dialog_el: Option<gpui::AnyElement> = launch_dialog_spec_ref
            .as_deref()
            .map(|spec_ref| self.render_launch_dialog(spec_ref, window, cx));

        root
            .relative() // needed so absolute-positioned dialog overlay works
            .child(titlebar)
            // Main content row: tree area + optional detail panel side-by-side
            .child(
                div()
                    .w_full()
                    .flex_1()
                    .flex()
                    .flex_row()
                    .overflow_hidden()
                    // Tree scroll area
                    .child(
                        div()
                            .flex_1()
                            .flex()
                            .justify_center()
                            .overflow_hidden()
                            .child(
                                div()
                                    .id("spec-scroll")
                                    .w_full()
                                    .max_w(MAX_CONTENT_WIDTH)
                                    .px_3()
                                    .py_3()
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .h_full()
                                    .overflow_y_scroll()
                                    .track_scroll(&scroll_handle)
                                    .children(status_banner)
                                    .children(root_node_el)
                                    .when(root_id.is_some(), |this| {
                                        this.child(div().w_full().border_t_1().border_color(rgb(colors.border)))
                                    })
                                    .children(extra_root_els),
                            ),
                    )
                    // Optional detail panel
                    .children(detail_panel_el),
            )
            // Optional message bar at the bottom
            .children(message_bar_el)
            // Optional launch dialog floating overlay
            .children(launch_dialog_el)
    }
}
