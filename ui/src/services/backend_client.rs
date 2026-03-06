use anyhow::Result;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RunId(pub u64);

#[derive(Clone, Debug)]
pub struct BackendClient {
    pub endpoint: String,
}

impl BackendClient {
    pub fn new(endpoint: impl Into<String>) -> Self {
        Self {
            endpoint: endpoint.into(),
        }
    }

    pub fn start_run(&self, spec_ref: &str) -> Result<RunId> {
        if spec_ref.trim().is_empty() {
            anyhow::bail!("spec_ref cannot be empty");
        }

        // Placeholder run id until API integration milestone.
        Ok(RunId(1))
    }
}
