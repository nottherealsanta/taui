use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message as WsMessage};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RunId(pub u64);

#[derive(Clone, Debug, Serialize)]
struct JsonRpcRequest {
    jsonrpc: &'static str,
    id: u64,
    method: String,
    params: serde_json::Value,
}

#[derive(Clone, Debug, Deserialize)]
#[allow(dead_code)]
struct JsonRpcResponse {
    jsonrpc: String,
    #[serde(default)]
    id: Option<u64>,
    #[serde(default)]
    result: Option<serde_json::Value>,
    #[serde(default)]
    error: Option<JsonRpcError>,
}

#[derive(Clone, Debug, Deserialize)]
#[allow(dead_code)]
struct JsonRpcError {
    code: i32,
    message: String,
    #[serde(default)]
    data: Option<serde_json::Value>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct TreeNode {
    pub id: String,
    pub spec_ref: String,
    pub depth: usize,
    pub markdown: String,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub collapsed: bool,
    #[serde(default)]
    pub code_refs: Vec<String>,
    #[serde(default)]
    pub verification: Option<String>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default)]
    pub related_to: Vec<String>,
}

/// Resolved code reference preview returned by `spec/getNodeCodeRefs`.
#[derive(Clone, Debug, Deserialize)]
pub struct CodeRefPreview {
    pub raw_ref: String,
    pub file_path: String,
    pub line_start: Option<i64>,
    pub line_end: Option<i64>,
    pub preview_start: Option<i64>,
    pub preview_end: Option<i64>,
    pub content: String,
    pub truncated: bool,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct CodeRefsResponse {
    pub refs: Vec<CodeRefPreview>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct TreeResponse {
    pub nodes: Vec<TreeNode>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct InitializeResponse {
    #[serde(rename = "protocolVersion")]
    pub protocol_version: String,
    #[serde(rename = "serverName")]
    pub server_name: String,
    pub workspace: Option<String>,
    pub capabilities: serde_json::Value,
}

#[derive(Clone, Debug, Deserialize)]
pub struct UpdateNodeResponse {
    #[serde(rename = "previous_spec_ref")]
    pub previous_spec_ref: String,
    pub node: TreeNode,
    #[serde(rename = "tree_changed")]
    pub tree_changed: bool,
}

/// Type alias for the pending-requests map shared between the call site and the read task.
type PendingMap = Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value>>>>>;

/// Live state of the persistent WebSocket connection.
#[derive(Debug)]
struct Connection {
    /// Send serialised JSON strings to the write task.
    sender: mpsc::Sender<String>,
    /// Correlates in-flight request IDs to their response channels.
    pending: PendingMap,
}

#[derive(Clone, Debug)]
pub struct BackendClient {
    pub endpoint: String,
    request_id: Arc<Mutex<u64>>,
    /// Established lazily on first call; reused for all subsequent calls.
    connection: Arc<Mutex<Option<Connection>>>,
}

impl BackendClient {
    pub fn new(endpoint: impl Into<String>) -> Self {
        Self {
            endpoint: endpoint.into(),
            request_id: Arc::new(Mutex::new(1)),
            connection: Arc::new(Mutex::new(None)),
        }
    }

    async fn next_id(&self) -> u64 {
        let mut id = self.request_id.lock().await;
        let next = *id;
        *id += 1;
        next
    }

    /// Return a reference to the live connection, creating it when necessary.
    /// If the existing connection's write channel is closed we reconnect.
    async fn get_connection(&self) -> Result<(mpsc::Sender<String>, PendingMap)> {
        let mut guard = self.connection.lock().await;

        // Reuse existing connection if the write side is still open.
        if let Some(ref conn) = *guard {
            if !conn.sender.is_closed() {
                return Ok((conn.sender.clone(), conn.pending.clone()));
            }
        }

        // Establish a fresh connection.
        let (ws_stream, _) = connect_async(&self.endpoint).await?;
        let (write, mut read) = ws_stream.split();

        let (tx, mut rx) = mpsc::channel::<String>(64);
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::new()));

        // Write task — forward queued messages to the WebSocket sink.
        let write = Arc::new(Mutex::new(write));
        {
            let write = write.clone();
            tokio::spawn(async move {
                while let Some(msg) = rx.recv().await {
                    let mut w = write.lock().await;
                    if w.send(WsMessage::Text(msg)).await.is_err() {
                        break;
                    }
                }
            });
        }

        // Read task — route each response to the correct pending oneshot.
        {
            let pending_read = pending.clone();
            tokio::spawn(async move {
                while let Some(msg) = read.next().await {
                    let Ok(WsMessage::Text(text)) = msg else {
                        continue;
                    };
                    let Ok(response) = serde_json::from_str::<JsonRpcResponse>(&text) else {
                        continue;
                    };
                    if let Some(id) = response.id {
                        let mut map = pending_read.lock().await;
                        if let Some(responder) = map.remove(&id) {
                            let result = if let Some(err) = response.error {
                                Err(anyhow::anyhow!(
                                    "RPC error {}: {}",
                                    err.code,
                                    err.message
                                ))
                            } else {
                                response
                                    .result
                                    .ok_or_else(|| anyhow::anyhow!("No result in response"))
                            };
                            let _ = responder.send(result);
                        }
                    }
                }
                // Connection lost — fail all in-flight requests.
                let mut map = pending_read.lock().await;
                for (_, responder) in map.drain() {
                    let _ =
                        responder.send(Err(anyhow::anyhow!("WebSocket connection closed")));
                }
            });
        }

        *guard = Some(Connection {
            sender: tx.clone(),
            pending: pending.clone(),
        });

        Ok((tx, pending))
    }

    async fn call_method(
        &self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let id = self.next_id().await;
        let request = JsonRpcRequest {
            jsonrpc: "2.0",
            id,
            method: method.to_string(),
            params,
        };
        let request_json = serde_json::to_string(&request)?;

        let (sender, pending) = self.get_connection().await?;

        // Register the response channel *before* sending so we cannot miss a fast reply.
        let (resp_tx, resp_rx) = oneshot::channel();
        pending.lock().await.insert(id, resp_tx);

        sender
            .send(request_json)
            .await
            .map_err(|_| anyhow::anyhow!("WebSocket write channel closed"))?;

        resp_rx
            .await
            .map_err(|_| anyhow::anyhow!("Response channel dropped"))?
    }

    pub async fn initialize(&self, workspace: Option<&str>) -> Result<InitializeResponse> {
        let response = self
            .call_method(
                "initialize",
                serde_json::json!({
                    "workspace": workspace
                }),
            )
            .await?;

        let result: InitializeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn get_tree_detailed(&self) -> Result<TreeResponse> {
        let response = self
            .call_method("spec/getTreeDetailed", serde_json::json!({}))
            .await?;
        let result: TreeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn update_node(
        &self,
        spec_ref: &str,
        patch: serde_json::Value,
    ) -> Result<UpdateNodeResponse> {
        let response = self
            .call_method(
                "spec/updateNode",
                serde_json::json!({
                    "spec_ref": spec_ref,
                    "patch": patch
                }),
            )
            .await?;

        let result: UpdateNodeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn create_sibling_node(&self, spec_ref: &str) -> Result<UpdateNodeResponse> {
        let response = self
            .call_method(
                "spec/createSiblingNode",
                serde_json::json!({
                    "spec_ref": spec_ref
                }),
            )
            .await?;

        let result: UpdateNodeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn indent_node(&self, spec_ref: &str) -> Result<UpdateNodeResponse> {
        let response = self
            .call_method(
                "spec/indentNode",
                serde_json::json!({
                    "spec_ref": spec_ref
                }),
            )
            .await?;

        let result: UpdateNodeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn outdent_node(&self, spec_ref: &str) -> Result<UpdateNodeResponse> {
        let response = self
            .call_method(
                "spec/outdentNode",
                serde_json::json!({
                    "spec_ref": spec_ref
                }),
            )
            .await?;

        let result: UpdateNodeResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub async fn set_node_collapsed(&self, spec_ref: &str, collapsed: bool) -> Result<TreeNode> {
        let response = self
            .call_method(
                "spec/setNodeCollapsed",
                serde_json::json!({
                    "spec_ref": spec_ref,
                    "collapsed": collapsed,
                }),
            )
            .await?;

        #[derive(Deserialize)]
        struct SetCollapsedResponse {
            node: TreeNode,
        }

        let result: SetCollapsedResponse = serde_json::from_value(response)?;
        Ok(result.node)
    }

    pub async fn get_node_code_refs(
        &self,
        spec_ref: &str,
        max_lines: Option<u32>,
    ) -> Result<CodeRefsResponse> {
        let mut params = serde_json::json!({ "spec_ref": spec_ref });
        if let Some(ml) = max_lines {
            params["max_lines"] = serde_json::json!(ml);
        }
        let response = self.call_method("spec/getNodeCodeRefs", params).await?;
        let result: CodeRefsResponse = serde_json::from_value(response)?;
        Ok(result)
    }

    pub fn start_run(&self, spec_ref: &str) -> Result<RunId> {
        if spec_ref.trim().is_empty() {
            anyhow::bail!("spec_ref cannot be empty");
        }

        Ok(RunId(1))
    }
}
