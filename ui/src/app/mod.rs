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

use crate::services::backend_client::{BackendClient, CodeRefPreview};
use crate::theme::ThemeRegistry;

use self::actions::{dispatch, UiAction};
use self::state::{AppState, BackendNode, BackendState, EditorMode, FlatNode, MetadataEditTarget, NodeId};
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
                .auto_grow(1, 20)
                .soft_wrap(true)
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

            let tree_result = client.get_tree_detailed().await;

            #[cfg(debug_assertions)]
            eprintln!("[perf] structural action round-trip: {:?}", t0.elapsed());

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

        cx.spawn(async move |this, cx| {
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

            // 4. Re-fetch tree so local optimistic state is reconciled.
            if let Ok(tree) = client.get_tree_detailed().await {
                this.update(&mut *cx, |shell, cx| {
                    let backend_nodes: Vec<BackendNode> = tree.nodes.into_iter().map(|n| BackendNode {
                        spec_ref: n.spec_ref,
                        depth: n.depth,
                        markdown: n.markdown,
                        status: n.status,
                        collapsed: n.collapsed,
                        code_refs: n.code_refs,
                        verification: n.verification,
                        depends_on: n.depends_on,
                        related_to: n.related_to,
                    }).collect();
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

    /// After a merge, sync the merged node to the backend and re-fetch.
    fn sync_merge_to_backend(&mut self, cx: &mut Context<Self>) {
        let Some(client) = self.client.clone() else { return };
        let Some(selected) = self.state.selected_node else { return };
        let spec_ref = self.state.nodes[selected].spec_ref.clone();
        let markdown = self.state.nodes[selected].markdown.clone();

        cx.spawn(async move |this, cx| {
            let _ = client.update_node(
                &spec_ref,
                serde_json::json!({ "markdown": markdown }),
            ).await;
            if let Ok(tree) = client.get_tree_detailed().await {
                this.update(&mut *cx, |shell, cx| {
                    let backend_nodes: Vec<BackendNode> = tree.nodes.into_iter().map(|n| BackendNode {
                        spec_ref: n.spec_ref,
                        depth: n.depth,
                        markdown: n.markdown,
                        status: n.status,
                        collapsed: n.collapsed,
                        code_refs: n.code_refs,
                        verification: n.verification,
                        depends_on: n.depends_on,
                        related_to: n.related_to,
                    }).collect();
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

        // Bullet marker - always shown; grows on row hover
        let bullet = div()
            .child("•")
            .text_color(rgb(colors.text_muted))
            .text_size(px(22.0))
            .group_hover(group_id.clone(), |s| s.text_size(px(28.0)));

        let chevron_slot = {
            let inner = chevron.unwrap_or_else(|| div().w(px(24.0)).into_any_element());
            div()
                .invisible()
                .group_hover(group_id.clone(), |s| s.visible())
                .child(inner)
        };
        let left_controls = div()
            .flex()
            .items_center()
            .gap_1()
            .child(chevron_slot)
            .child(bullet);

        let is_active_editor = self.editor_mode == EditorMode::Editing
            && self.editing_node_id == Some(node_id);
        let is_empty = row.markdown.trim().is_empty();

        // Content area
        let content_area = if is_active_editor {
            let markdown_input = self.markdown_input.clone();
            let editor_markdown = self.markdown_input.read(cx).value().to_string();
            let (editor_text_size, editor_weight) = markdown_edit_style(&editor_markdown);
            div()
                .flex_1()
                .pt(px(4.0))
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
            let markdown_view_id = ("node-markdown", node_id);
            let markdown_style = self.get_markdown_style();
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
                    TextView::markdown(markdown_view_id, row.markdown.clone(), window, cx)
                        .style(markdown_style)
                        .text_size(MARKDOWN_TEXT_SIZE)
                        .line_height(relative(MARKDOWN_LINE_HEIGHT))
                        .text_color(rgb(colors.text)),
                )
        };

        let padding = if is_root {
            (px(14.0), px(10.0))
        } else {
            (px(10.0), px(2.0))
        };

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
            });

        row_el = row_el.child(
            div()
                .flex()
                .items_start()
                .gap_1()
                .child(left_controls.pt(px(0.0)))
                .child(content_area),
        );

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
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> gpui::AnyElement {
        let colors = self.theme.styles.colors.clone();

        // Build a FlatNode snapshot for render_row (avoids restructuring that function).
        let node = &self.state.nodes[node_id];
        let is_selected = self.state.selected_node == Some(node_id);

        let flat = FlatNode {
            id: node_id,
            depth: 0, // depth irrelevant — no per-row indent in new layout
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
                        .ml(px(20.0))
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
        let children_el: Option<gpui::AnyElement> = if !is_collapsed && !children_ids.is_empty() {
            // Propagate highlight downward: children of the selected node (or
            // a node whose ancestor is selected) should also be highlighted.
            let child_ancestor_selected = is_selected || ancestor_is_selected;
            let child_els: Vec<gpui::AnyElement> = children_ids
                .iter()
                .map(|&cid| self.render_node(cid, false, child_ancestor_selected, window, cx))
                .collect();

            Some(
                div()
                    .pl(INDENT_PER_LEVEL)
                    .ml(px(20.0)) // align left border under the bullet
                    .border_l_1()
                    .border_color(rgb(colors.border_variant))
                    .flex()
                    .flex_col()
                    .children(child_els)
                    .into_any_element(),
            )
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
            self.render_node(id, true, false, window, cx)
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
            .map(|id| self.render_node(id, false, false, window, cx))
            .collect();

        root
            .child(titlebar)
            .child(
                div()
                    .w_full()
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
    }
}
