#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IndexedSpecNode {
    pub title: String,
    pub depth: usize,
    pub spec_ref: String,
}

#[derive(Clone, Debug, Default)]
pub struct SpecIndex {
    pub nodes: Vec<IndexedSpecNode>,
}

impl SpecIndex {
    pub fn from_markdown(spec_path: &str, markdown: &str) -> Self {
        let mut nodes = Vec::new();

        for line in markdown.lines() {
            let indent = line.chars().take_while(|ch| *ch == ' ').count();
            let trimmed = line.trim_start();
            if !(trimmed.starts_with("- ")
                || trimmed.starts_with("* ")
                || trimmed.starts_with("+ "))
            {
                continue;
            }

            let depth = (indent / 4) + 1;
            let title = trimmed[2..].trim();
            if title.is_empty() {
                continue;
            }

            let anchor = slugify(title);
            nodes.push(IndexedSpecNode {
                title: title.to_string(),
                depth,
                spec_ref: format!("{spec_path}#{anchor}"),
            });
        }

        Self { nodes }
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
