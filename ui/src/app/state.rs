use std::collections::HashMap;

pub type NodeId = usize;

pub type SpecRef = String;

#[derive(Clone, Debug)]
pub struct SpecNode {
    pub id: NodeId,
    pub spec_ref: SpecRef,
    pub markdown: String,
    pub parent: Option<NodeId>,
    pub children: Vec<NodeId>,
    pub collapsed: bool,
}

#[derive(Clone, Debug)]
pub struct FlatNode {
    pub id: NodeId,
    pub depth: usize,
    pub markdown: String,
    pub selected: bool,
    pub collapsed: bool,
    pub has_children: bool,
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

        let mut depth_stack: Vec<Option<NodeId>> = Vec::new();

        for bn in nodes {
            let depth = bn.depth;
            let parent_id = if depth == 0 {
                None
            } else {
                depth_stack.get(depth.saturating_sub(1)).copied().flatten()
            };

            let collapsed = parse_collapsed_metadata(&bn.markdown);

            let id = self.create_node(bn.spec_ref.clone(), bn.markdown, parent_id);

            self.nodes[id].collapsed = collapsed;

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
        });
        id
    }

    pub fn flattened_nodes(&self) -> Vec<FlatNode> {
        let mut out = Vec::new();
        for root in &self.root_nodes {
            self.collect_flat(*root, 0, &mut out);
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
        if let Some(root_id) = self.primary_root_id() {
            for child_id in &self.nodes[root_id].children {
                self.collect_flat(*child_id, 1, &mut out);
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

    fn collect_flat(&self, node_id: NodeId, depth: usize, out: &mut Vec<FlatNode>) {
        let node = &self.nodes[node_id];
        let has_children = !node.children.is_empty();

        out.push(FlatNode {
            id: node.id,
            depth,
            markdown: node.markdown.clone(),
            selected: self.selected_node == Some(node.id),
            collapsed: node.collapsed,
            has_children,
        });

        if !node.collapsed {
            for child_id in &node.children {
                self.collect_flat(*child_id, depth + 1, out);
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

                let collapsed = self.nodes[selected].collapsed;
                let markdown = &mut self.nodes[selected].markdown;
                *markdown = update_collapsed_metadata(markdown, collapsed);

                return true;
            }
        }
        false
    }
}

fn parse_collapsed_metadata(markdown: &str) -> bool {
    for line in markdown.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("{{") && trimmed.ends_with("}}") {
            if trimmed.contains("collapsed:") {
                return trimmed.contains("true");
            }
        }
    }
    false
}

fn update_collapsed_metadata(markdown: &str, collapsed: bool) -> String {
    let mut lines: Vec<String> = markdown.lines().map(|s| s.to_string()).collect();
    let mut found = false;

    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("{{") && trimmed.ends_with("}}") && trimmed.contains("collapsed:") {
            *line = format!("{{{{collapsed: {}}}}}", collapsed);
            found = true;
            break;
        }
    }

    if !found {
        let metadata_line = format!("{{{{collapsed: {}}}}}", collapsed);
        if lines.is_empty() {
            lines.push(metadata_line);
        } else {
            lines.insert(1, metadata_line);
        }
    }

    lines.join("\n")
}

/// A node payload arriving from the backend.
#[derive(Clone, Debug)]
pub struct BackendNode {
    pub spec_ref: SpecRef,
    pub depth: usize,
    pub markdown: String,
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
    fn test_parse_collapsed_metadata() {
        assert!(parse_collapsed_metadata("{{collapsed: true}}"));
        assert!(!parse_collapsed_metadata("{{collapsed: false}}"));
        assert!(!parse_collapsed_metadata("Some content"));
        assert!(parse_collapsed_metadata(
            "Line 1\n{{collapsed: true}}\nLine 2"
        ));
    }

    #[test]
    fn test_update_collapsed_metadata() {
        let content = "Some content";
        let updated = update_collapsed_metadata(content, true);
        assert!(updated.contains("{{collapsed: true}}"));

        let content_with_meta = "{{collapsed: false}}\nSome content";
        let updated = update_collapsed_metadata(content_with_meta, true);
        assert!(updated.contains("{{collapsed: true}}"));
        assert!(!updated.contains("{{collapsed: false}}"));
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
                markdown: "Root\n{{collapsed: true}}".to_string(),
            },
            BackendNode {
                spec_ref: "b".to_string(),
                depth: 1,
                markdown: "Child".to_string(),
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
