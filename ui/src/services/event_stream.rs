use std::time::Duration;

use super::backend_client::RunId;

#[derive(Clone, Debug)]
pub struct AgentEvent {
    pub spec_ref: String,
    pub message: String,
}

#[derive(Clone, Debug)]
pub struct EventStream {
    pub reconnect_backoff: Duration,
}

impl EventStream {
    pub fn new() -> Self {
        Self {
            reconnect_backoff: Duration::from_millis(500),
        }
    }

    pub fn subscribe_events(&self, run_id: RunId) -> Vec<AgentEvent> {
        vec![AgentEvent {
            spec_ref: "ui/specs/_main.md#taui-ui".to_string(),
            message: format!("subscribed to run {}", run_id.0),
        }]
    }
}
