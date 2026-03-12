use std::collections::HashMap;

pub type NodeId = usize;

pub type SpecRef = String;

/// The two interactive modes of the spec tree editor, plus an idle state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EditorMode {
    /// No node is focused or selected.
    Normal,
    /// A node is highlighted (blue background) but the text cursor is not active.
    Selection,
    /// The text cursor is active inside a node's input area.
    Editing,
}

/// Identifies which metadata item is currently being edited inline.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MetadataEditTarget {
    CodeRef { node_id: NodeId, ref_index: usize },
    Verification { node_id: NodeId },
    DependsOn { node_id: NodeId, index: usize },
    RelatedTo { node_id: NodeId, index: usize },
}

#[derive(Clone, Debug)]
pub struct SpecNode {
    pub id: NodeId,
    pub spec_ref: SpecRef,
    pub markdown: String,
    pub parent: Option<NodeId>,
    pub children: Vec<NodeId>,
    pub collapsed: bool,
    pub status: Option<String>,
    pub code_refs: Vec<String>,
    pub verification: Option<String>,
    pub depends_on: Vec<String>,
    pub related_to: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct FlatNode {
    pub id: NodeId,
    pub depth: usize,
    pub markdown: String,
    pub selected: bool,
    /// True when this node should receive a selection-mode blue highlight
    /// (i.e. it is the selected node or a visible descendant of it).
    pub selection_highlighted: bool,
    pub collapsed: bool,
    pub has_children: bool,
    pub code_refs: Vec<String>,
    pub verification: Option<String>,
    pub depends_on: Vec<String>,
    pub related_to: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BackendState {
    Offline,
    Loading,
    Ready,
    Error(String),
}

#[derive(Clone, Debug)]
pub struct AppState {
    pub nodes: Vec<SpecNode>,
    pub root_nodes: Vec<NodeId>,
    pub spec_ref_index: HashMap<SpecRef, NodeId>,
    pub selected_node: Option<NodeId>,
    pub selected_spec_ref: Option<SpecRef>,
    pub chat_draft: String,
    pub backend_state: BackendState,
}

impl AppState {
    pub fn demo() -> Self {
        let mut state = Self {
            nodes: Vec::new(),
            root_nodes: Vec::new(),
            spec_ref_index: HashMap::new(),
            selected_node: None,
            selected_spec_ref: None,
            chat_draft: String::new(),
            backend_state: BackendState::Offline,
        };

        let root = state.create_node(
            "specs/_main.md#taui-ui".to_string(),
            "Taui UI\nNative desktop shell with spec-first workflow".to_string(),
            None,
        );
        state.root_nodes.push(root);

        let spec_tree = state.create_node(
            "specs/_main.md#spec-tree-pane".to_string(),
            "Spec Tree Pane\nPrimary interaction surface for authoring and selecting nodes"
                .to_string(),
            Some(root),
        );
        state.nodes[root].children.push(spec_tree);

        let execution = state.create_node(
            "specs/_main.md#execution-stream".to_string(),
            "Execution Stream\nLive events and Box inspector".to_string(),
            Some(root),
        );
        state.nodes[root].children.push(execution);

        let editing = state.create_node(
            "specs/_main.md#editable-nodes".to_string(),
            "Editable Nodes\nTyping updates selected node markdown".to_string(),
            Some(spec_tree),
        );
        state.nodes[spec_tree].children.push(editing);

        let tab_indent = state.create_node(
            "specs/_main.md#tab-indent".to_string(),
            "Tab Indent\nTab makes selected node a child of previous sibling".to_string(),
            Some(spec_tree),
        );
        state.nodes[spec_tree].children.push(tab_indent);

        state.selected_node = Some(spec_tree);
        state.selected_spec_ref = Some(state.nodes[spec_tree].spec_ref.clone());
        state
    }

    pub fn hydrate_from_backend(&mut self, nodes: Vec<BackendNode>) {
        let prev_selected_ref = self.selected_spec_ref.clone();

        self.nodes.clear();
        self.root_nodes.clear();
        self.spec_ref_index.clear();

        // The backend may start depths at 1 (or any positive value). Normalise
        // so that the shallowest node is always at depth 0, making it a root.
        let min_depth = nodes.iter().map(|n| n.depth).min().unwrap_or(0);

        let mut depth_stack: Vec<Option<NodeId>> = Vec::new();

        for bn in nodes {
            let depth = bn.depth.saturating_sub(min_depth);
            let parent_id = if depth == 0 {
                None
            } else {
                depth_stack.get(depth.saturating_sub(1)).copied().flatten()
            };

            let id = self.create_node(bn.spec_ref.clone(), bn.markdown, parent_id);
            self.nodes[id].collapsed = bn.collapsed;
            self.nodes[id].status = bn.status;
            self.nodes[id].code_refs = bn.code_refs;
            self.nodes[id].verification = bn.verification;
            self.nodes[id].depends_on = bn.depends_on;
            self.nodes[id].related_to = bn.related_to;

            if let Some(p) = parent_id {
                self.nodes[p].children.push(id);
            } else {
                self.root_nodes.push(id);
            }

            if depth_stack.len() <= depth {
                depth_stack.resize(depth + 1, None);
            }
            depth_stack[depth] = Some(id);
            if depth_stack.len() > depth + 1 {
                depth_stack.truncate(depth + 1);
            }
        }

        self.selected_node = prev_selected_ref
            .as_deref()
            .and_then(|prev_ref| self.spec_ref_index.get(prev_ref).copied());
        self.selected_spec_ref = self
            .selected_node
            .map(|id| self.nodes[id].spec_ref.clone())
            .or(prev_selected_ref);

        // Drop root nodes that are empty placeholders (no markdown, no children).
        // The backend parser can produce these as artifacts of blank lines or
        // the implicit list-item wrapping at the top of a spec file.
        self.root_nodes.retain(|&id| {
            !self.nodes[id].markdown.trim().is_empty() || !self.nodes[id].children.is_empty()
        });

        if let Some(root_id) = self.primary_root_id() {
            self.nodes[root_id].collapsed = false;
        }

        self.backend_state = BackendState::Ready;
    }

    pub fn create_node(
        &mut self,
        spec_ref: SpecRef,
        markdown: String,
        parent: Option<NodeId>,
    ) -> NodeId {
        let id = self.nodes.len();
        self.spec_ref_index.insert(spec_ref.clone(), id);
        self.nodes.push(SpecNode {
            id,
            spec_ref,
            markdown,
            parent,
            children: Vec::new(),
            collapsed: false,
            status: None,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        });
        id
    }

    pub fn flattened_nodes(&self) -> Vec<FlatNode> {
        let mut out = Vec::new();
        for root in &self.root_nodes {
            self.collect_flat(*root, 0, false, &mut out);
        }
        out
    }

    pub fn primary_root_id(&self) -> Option<NodeId> {
        self.root_nodes.first().copied()
    }

    pub fn primary_root(&self) -> Option<&SpecNode> {
        self.primary_root_id().map(|id| &self.nodes[id])
    }

    pub fn is_primary_root(&self, id: NodeId) -> bool {
        self.primary_root_id() == Some(id)
    }

    pub fn flattened_tree_nodes(&self) -> Vec<FlatNode> {
        let mut out = Vec::new();
        let root_id = self.primary_root_id();
        for &rid in &self.root_nodes {
            if Some(rid) == root_id {
                // Primary root: render its children at depth 1.
                for child_id in &self.nodes[rid].children {
                    self.collect_flat(*child_id, 1, false, &mut out);
                }
            } else {
                // Additional roots (e.g. from linked spec files): render at depth 1.
                self.collect_flat(rid, 1, false, &mut out);
            }
        }
        out
    }

    pub fn siblings(&self, parent: Option<NodeId>) -> &[NodeId] {
        match parent {
            Some(parent_id) => &self.nodes[parent_id].children,
            None => &self.root_nodes,
        }
    }

    pub fn siblings_mut(&mut self, parent: Option<NodeId>) -> &mut Vec<NodeId> {
        match parent {
            Some(parent_id) => &mut self.nodes[parent_id].children,
            None => &mut self.root_nodes,
        }
    }

    pub fn set_selected(&mut self, id: NodeId) {
        self.selected_node = Some(id);
        self.selected_spec_ref = Some(self.nodes[id].spec_ref.clone());
    }

    pub fn selected_markdown_mut(&mut self) -> Option<&mut String> {
        let selected = self.selected_node?;
        Some(&mut self.nodes[selected].markdown)
    }

    pub fn selected_spec_ref(&self) -> Option<&str> {
        self.selected_spec_ref.as_deref()
    }

    /// Collect the node and its visible descendants into `out`.
    /// `ancestor_selected` is true when an ancestor is the selected node,
    /// meaning all visible descendants should be selection-highlighted.
    fn collect_flat(
        &self,
        node_id: NodeId,
        depth: usize,
        ancestor_selected: bool,
        out: &mut Vec<FlatNode>,
    ) {
        let node = &self.nodes[node_id];
        let has_children = !node.children.is_empty();
        let is_selected = self.selected_node == Some(node.id);
        let selection_highlighted = is_selected || ancestor_selected;

        out.push(FlatNode {
            id: node.id,
            depth,
            markdown: node.markdown.clone(),
            selected: is_selected,
            selection_highlighted,
            collapsed: node.collapsed,
            has_children,
            code_refs: node.code_refs.clone(),
            verification: node.verification.clone(),
            depends_on: node.depends_on.clone(),
            related_to: node.related_to.clone(),
        });

        if !node.collapsed {
            for child_id in &node.children {
                self.collect_flat(*child_id, depth + 1, selection_highlighted, out);
            }
        }
    }

    pub fn toggle_collapse(&mut self) -> bool {
        if let Some(selected) = self.selected_node {
            if self.is_primary_root(selected) {
                return false;
            }
            if !self.nodes[selected].children.is_empty() {
                self.nodes[selected].collapsed = !self.nodes[selected].collapsed;
                return true;
            }
        }
        false
    }

    // -------------------------------------------------------------------------
    // Tree mutation helpers (used by editor key handlers)
    // -------------------------------------------------------------------------

    /// Split the currently selected node at `byte_offset`.
    ///
    /// Returns `(new_node_id, insert_as_first_child)` where `insert_as_first_child`
    /// indicates whether the new node was placed as a first child (true) or next
    /// sibling (false).
    ///
    /// The caller is responsible for updating the flat-tree cache.
    pub fn split_selected_at(&mut self, byte_offset: usize) -> Option<NodeId> {
        let selected = self.selected_node?;
        let text = self.nodes[selected].markdown.clone();

        // Clamp offset to valid UTF-8 boundary
        let byte_offset = byte_offset.min(text.len());
        // Walk forward until we're on a char boundary
        let byte_offset = {
            let mut o = byte_offset;
            while o < text.len() && !text.is_char_boundary(o) {
                o += 1;
            }
            o
        };

        let fst = text[..byte_offset].to_string();
        let snd = text[byte_offset..].trim_start_matches('\n').to_string();

        let parent = self.nodes[selected].parent;
        let has_children = !self.nodes[selected].children.is_empty();

        // Update the current node's text to the first half.
        self.nodes[selected].markdown = fst;

        // Generate a temporary spec_ref for the new node.
        let tmp_ref: SpecRef = format!("local/new-{}", self.nodes.len());
        let new_parent = if has_children { Some(selected) } else { parent };
        let new_id = self.create_node(tmp_ref, snd, new_parent);

        if has_children {
            // Insert as first child of the current node so tree structure is preserved.
            self.nodes[selected].children.insert(0, new_id);
        } else {
            // Insert as next sibling.
            let insertion_index = self
                .siblings(parent)
                .iter()
                .position(|id| *id == selected)
                .map(|i| i + 1)
                .unwrap_or_else(|| self.siblings(parent).len());
            self.siblings_mut(parent).insert(insertion_index, new_id);
        }

        self.set_selected(new_id);
        Some(new_id)
    }

    /// Merge the currently selected node's text onto the end of the previous
    /// visible node, re-parent current node's children to that previous node,
    /// and remove the current node from the tree.
    ///
    /// Returns `(target_node_id, join_byte_offset)` – the node that absorbs the
    /// content and the byte offset within its (new) markdown where the two texts
    /// were joined.  The caller should position the cursor there.
    pub fn merge_selected_into_previous(&mut self) -> Option<(NodeId, usize)> {
        let selected = self.selected_node?;

        // Find the previous visible node from the full flattened list.
        let flat = self.flattened_nodes();
        let current_idx = flat.iter().position(|n| n.id == selected)?;
        if current_idx == 0 {
            return None;
        }
        let prev_id = flat[current_idx - 1].id;

        // We cannot merge into the primary root.
        if self.is_primary_root(prev_id) {
            return None;
        }

        let join_offset = self.nodes[prev_id].markdown.len();
        let current_text = self.nodes[selected].markdown.clone();

        // Append current text to previous node.
        self.nodes[prev_id].markdown.push_str(&current_text);

        // Re-parent children of the deleted node to the previous node.
        let children: Vec<NodeId> = self.nodes[selected].children.clone();
        for &child_id in &children {
            self.nodes[child_id].parent = Some(prev_id);
        }
        self.nodes[prev_id].children.extend(children);
        self.nodes[selected].children.clear();

        // Remove current node from its parent's child list.
        let parent = self.nodes[selected].parent;
        self.siblings_mut(parent).retain(|&id| id != selected);

        self.set_selected(prev_id);
        Some((prev_id, join_offset))
    }

    /// Merge the next visible node's text into the currently selected node,
    /// re-parent its children, and remove the next node from the tree.
    ///
    /// Returns the byte offset of the cursor after the merge (end of the
    /// original selected node's text, before the appended content).
    pub fn merge_next_into_selected(&mut self) -> Option<usize> {
        let selected = self.selected_node?;

        let flat = self.flattened_nodes();
        let current_idx = flat.iter().position(|n| n.id == selected)?;
        let next_id = flat.get(current_idx + 1)?.id;

        // We cannot merge the primary root.
        if self.is_primary_root(next_id) {
            return None;
        }

        let join_offset = self.nodes[selected].markdown.len();
        let next_text = self.nodes[next_id].markdown.clone();

        // Append next node's text to the selected node.
        self.nodes[selected].markdown.push_str(&next_text);

        // Re-parent children.
        let children: Vec<NodeId> = self.nodes[next_id].children.clone();
        for &child_id in &children {
            self.nodes[child_id].parent = Some(selected);
        }
        self.nodes[selected].children.extend(children);
        self.nodes[next_id].children.clear();

        // Remove next node from its parent.
        let next_parent = self.nodes[next_id].parent;
        self.siblings_mut(next_parent).retain(|&id| id != next_id);

        Some(join_offset)
    }
}

/// A node payload arriving from the backend.
#[derive(Clone, Debug)]
pub struct BackendNode {
    pub spec_ref: SpecRef,
    pub depth: usize,
    pub markdown: String,
    pub status: Option<String>,
    pub collapsed: bool,
    pub code_refs: Vec<String>,
    pub verification: Option<String>,
    pub depends_on: Vec<String>,
    pub related_to: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn first_line(markdown: &str) -> &str {
        markdown.lines().next().unwrap_or("")
    }

    fn make_backend_node(spec_ref: &str, markdown: &str, depth: usize) -> BackendNode {
        BackendNode {
            spec_ref: spec_ref.to_string(),
            depth,
            markdown: markdown.to_string(),
            status: None,
            collapsed: false,
            code_refs: Vec::new(),
            verification: None,
            depends_on: Vec::new(),
            related_to: Vec::new(),
        }
    }

    #[test]
    fn test_toggle_collapse() {
        let mut state = AppState::demo();
        let root = state.root_nodes[0];
        let child = state.nodes[root].children[0];
        state.set_selected(child);

        assert!(state.nodes[child].children.len() > 0);
        assert!(!state.nodes[child].collapsed);

        assert!(state.toggle_collapse());
        assert!(state.nodes[child].collapsed);

        assert!(state.toggle_collapse());
        assert!(!state.nodes[child].collapsed);
    }

    #[test]
    fn test_collapsed_flattening_hides_children() {
        let mut state = AppState::demo();
        let root = state.root_nodes[0];

        let flat_before = state.flattened_nodes();
        let count_before = flat_before.len();

        state.nodes[root].collapsed = true;

        let flat_after = state.flattened_nodes();
        assert!(flat_after.len() < count_before);
    }

    #[test]
    fn hydrate_flat_list_builds_root_nodes() {
        let mut state = AppState::demo();
        state.hydrate_from_backend(vec![
            make_backend_node("specs/a.md#foo", "Foo", 0),
            make_backend_node("specs/a.md#bar", "Bar", 0),
        ]);
        assert_eq!(state.root_nodes.len(), 2);
        assert_eq!(state.nodes.len(), 2);
        assert_eq!(first_line(&state.nodes[0].markdown), "Foo");
        assert_eq!(first_line(&state.nodes[1].markdown), "Bar");
    }

    #[test]
    fn hydrate_nested_list_builds_parent_child_links() {
        let mut state = AppState::demo();
        state.hydrate_from_backend(vec![
            make_backend_node("specs/a.md#root", "Root", 0),
            make_backend_node("specs/a.md#child", "Child", 1),
            make_backend_node("specs/a.md#grandchild", "Grandchild", 2),
        ]);
        assert_eq!(state.root_nodes.len(), 1);
        let root_id = state.root_nodes[0];
        let child_id = state.nodes[root_id].children[0];
        let grandchild_id = state.nodes[child_id].children[0];
        assert_eq!(first_line(&state.nodes[root_id].markdown), "Root");
        assert_eq!(first_line(&state.nodes[child_id].markdown), "Child");
        assert_eq!(
            first_line(&state.nodes[grandchild_id].markdown),
            "Grandchild"
        );
        assert_eq!(state.nodes[child_id].parent, Some(root_id));
        assert_eq!(state.nodes[grandchild_id].parent, Some(child_id));
    }

    #[test]
    fn hydrate_sibling_after_nested_child() {
        let mut state = AppState::demo();
        state.hydrate_from_backend(vec![
            make_backend_node("a", "Root", 0),
            make_backend_node("b", "Child", 1),
            make_backend_node("c", "GrandChild", 2),
            make_backend_node("d", "Sibling", 1),
        ]);
        let root_id = state.root_nodes[0];
        assert_eq!(state.nodes[root_id].children.len(), 2);
        let sibling_id = state.nodes[root_id].children[1];
        assert_eq!(first_line(&state.nodes[sibling_id].markdown), "Sibling");
        assert_eq!(state.nodes[sibling_id].parent, Some(root_id));
    }

    #[test]
    fn hydrate_clears_previous_tree() {
        let mut state = AppState::demo();
        let prev_count = state.nodes.len();
        assert!(prev_count > 0);
        state.hydrate_from_backend(vec![make_backend_node("specs/x.md#only", "Only", 0)]);
        assert_eq!(state.nodes.len(), 1);
        assert_eq!(state.root_nodes.len(), 1);
    }

    #[test]
    fn hydrate_preserves_selection_by_spec_ref() {
        let mut state = AppState::demo();
        state.selected_spec_ref = Some("specs/a.md#kept".to_string());
        state.hydrate_from_backend(vec![
            make_backend_node("specs/a.md#other", "Other", 0),
            make_backend_node("specs/a.md#kept", "Kept", 0),
        ]);
        assert!(state.selected_node.is_some());
        let sel = state.selected_node.unwrap();
        assert_eq!(state.nodes[sel].spec_ref, "specs/a.md#kept");
    }

    #[test]
    fn hydrate_drops_selection_when_ref_gone() {
        let mut state = AppState::demo();
        state.selected_spec_ref = Some("specs/a.md#gone".to_string());
        state.hydrate_from_backend(vec![make_backend_node("specs/a.md#other", "Other", 0)]);
        assert!(state.selected_node.is_none());
    }

    #[test]
    fn hydrate_sets_backend_state_ready() {
        let mut state = AppState::demo();
        state.backend_state = BackendState::Loading;
        state.hydrate_from_backend(vec![]);
        assert_eq!(state.backend_state, BackendState::Ready);
    }

    #[test]
    fn hydrate_builds_spec_ref_index() {
        let mut state = AppState::demo();
        state.hydrate_from_backend(vec![
            make_backend_node("specs/f.md#alpha", "Alpha", 0),
            make_backend_node("specs/f.md#beta", "Beta", 0),
        ]);
        assert!(state.spec_ref_index.contains_key("specs/f.md#alpha"));
        assert!(state.spec_ref_index.contains_key("specs/f.md#beta"));
        let alpha_id = state.spec_ref_index["specs/f.md#alpha"];
        assert_eq!(first_line(&state.nodes[alpha_id].markdown), "Alpha");
    }

    #[test]
    fn flattened_tree_nodes_excludes_primary_root() {
        let state = AppState::demo();
        let root_id = state.primary_root_id().unwrap();
        let tree_nodes = state.flattened_tree_nodes();

        let tree_node_ids: Vec<_> = tree_nodes.iter().map(|n| n.id).collect();
        assert!(!tree_node_ids.contains(&root_id));
    }

    #[test]
    fn flattened_tree_nodes_contains_root_children() {
        let state = AppState::demo();
        let root_id = state.primary_root_id().unwrap();
        let root_children = state.nodes[root_id].children.clone();

        let tree_nodes = state.flattened_tree_nodes();
        let tree_node_ids: Vec<_> = tree_nodes.iter().map(|n| n.id).collect();

        for child_id in root_children {
            assert!(tree_node_ids.contains(&child_id));
        }
    }

    #[test]
    fn toggle_collapse_primary_root_is_noop() {
        let mut state = AppState::demo();
        let root = state.root_nodes[0];
        state.set_selected(root);

        assert!(!state.toggle_collapse());
        assert!(!state.nodes[root].collapsed);
    }

    #[test]
    fn hydrate_forces_primary_root_not_collapsed() {
        let mut state = AppState::demo();
        state.hydrate_from_backend(vec![
            BackendNode {
                spec_ref: "a".to_string(),
                depth: 0,
                markdown: "Root".to_string(),
                status: None,
                collapsed: true,
                code_refs: Vec::new(),
                verification: None,
                depends_on: Vec::new(),
                related_to: Vec::new(),
            },
            BackendNode {
                spec_ref: "b".to_string(),
                depth: 1,
                markdown: "Child".to_string(),
                status: None,
                collapsed: false,
                code_refs: Vec::new(),
                verification: None,
                depends_on: Vec::new(),
                related_to: Vec::new(),
            },
        ]);

        let root_id = state.primary_root_id().unwrap();
        assert!(!state.nodes[root_id].collapsed);
    }

    #[test]
    fn primary_root_id_returns_first_root() {
        let state = AppState::demo();
        let root_id = state.primary_root_id();
        assert!(root_id.is_some());
        assert_eq!(root_id, Some(state.root_nodes[0]));
    }

    #[test]
    fn is_primary_root_identifies_root() {
        let state = AppState::demo();
        let root_id = state.root_nodes[0];
        let child_id = state.nodes[root_id].children[0];

        assert!(state.is_primary_root(root_id));
        assert!(!state.is_primary_root(child_id));
    }
}
