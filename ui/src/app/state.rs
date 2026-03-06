use std::fmt;

pub type NodeId = usize;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NodeStatus {
    Draft,
    Ready,
    InProgress,
    Done,
    Blocked,
}

impl NodeStatus {
    pub fn next(self) -> Self {
        match self {
            Self::Draft => Self::Ready,
            Self::Ready => Self::InProgress,
            Self::InProgress => Self::Done,
            Self::Done => Self::Blocked,
            Self::Blocked => Self::Draft,
        }
    }
}

impl fmt::Display for NodeStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Self::Draft => "draft",
            Self::Ready => "ready",
            Self::InProgress => "in_progress",
            Self::Done => "done",
            Self::Blocked => "blocked",
        };
        write!(f, "{label}")
    }
}

#[derive(Clone, Debug)]
pub struct SpecNode {
    pub id: NodeId,
    pub title: String,
    pub intent: String,
    pub status: NodeStatus,
    pub parent: Option<NodeId>,
    pub children: Vec<NodeId>,
}

#[derive(Clone, Debug)]
pub struct FlatNode {
    pub id: NodeId,
    pub depth: usize,
    pub title: String,
    pub status: NodeStatus,
    pub selected: bool,
}

#[derive(Clone, Debug)]
pub struct AppState {
    pub nodes: Vec<SpecNode>,
    pub root_nodes: Vec<NodeId>,
    pub selected_node: Option<NodeId>,
    pub selected_spec_ref: Option<String>,
    pub edit_mode: bool,
    pub chat_target: String,
    pub chat_draft: String,
}

impl AppState {
    pub fn demo() -> Self {
        let mut state = Self {
            nodes: Vec::new(),
            root_nodes: Vec::new(),
            selected_node: None,
            selected_spec_ref: None,
            edit_mode: true,
            chat_target: "root".to_string(),
            chat_draft: String::new(),
        };

        let root = state.create_node(
            "Taui UI".to_string(),
            "Native desktop shell with spec-first workflow".to_string(),
            NodeStatus::InProgress,
            None,
        );
        state.root_nodes.push(root);

        let spec_tree = state.create_node(
            "Spec Tree Pane".to_string(),
            "Primary interaction surface for authoring and selecting nodes".to_string(),
            NodeStatus::Ready,
            Some(root),
        );
        state.nodes[root].children.push(spec_tree);

        let execution = state.create_node(
            "Execution Stream".to_string(),
            "Live events and Box inspector".to_string(),
            NodeStatus::Draft,
            Some(root),
        );
        state.nodes[root].children.push(execution);

        let editing = state.create_node(
            "Editable Nodes".to_string(),
            "Typing updates selected node title".to_string(),
            NodeStatus::Ready,
            Some(spec_tree),
        );
        state.nodes[spec_tree].children.push(editing);

        let tab_indent = state.create_node(
            "Tab Indent".to_string(),
            "Tab makes selected node a child of previous sibling".to_string(),
            NodeStatus::Ready,
            Some(spec_tree),
        );
        state.nodes[spec_tree].children.push(tab_indent);

        state.selected_node = Some(spec_tree);
        state.recompute_spec_ref();
        state
    }

    pub fn create_node(
        &mut self,
        title: String,
        intent: String,
        status: NodeStatus,
        parent: Option<NodeId>,
    ) -> NodeId {
        let id = self.nodes.len();
        self.nodes.push(SpecNode {
            id,
            title,
            intent,
            status,
            parent,
            children: Vec::new(),
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
        self.recompute_spec_ref();
    }

    pub fn selected_title_mut(&mut self) -> Option<&mut String> {
        let selected = self.selected_node?;
        Some(&mut self.nodes[selected].title)
    }

    pub fn selected_spec_ref(&self) -> Option<&str> {
        self.selected_spec_ref.as_deref()
    }

    pub fn spec_ref_for_node(&self, node_id: NodeId) -> String {
        let anchor = slugify(&self.nodes[node_id].title);
        format!("ui/specs/_main.md#{anchor}")
    }

    pub fn recompute_spec_ref(&mut self) {
        self.selected_spec_ref = self.selected_node.map(|id| self.spec_ref_for_node(id));
    }

    fn collect_flat(&self, node_id: NodeId, depth: usize, out: &mut Vec<FlatNode>) {
        let node = &self.nodes[node_id];
        out.push(FlatNode {
            id: node.id,
            depth,
            title: node.title.clone(),
            status: node.status,
            selected: self.selected_node == Some(node.id),
        });

        for child_id in &node.children {
            self.collect_flat(*child_id, depth + 1, out);
        }
    }
}

fn slugify(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut prev_dash = false;

    for ch in input.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }

    let out = out.trim_matches('-').to_string();
    if out.is_empty() {
        "untitled".to_string()
    } else {
        out
    }
}
