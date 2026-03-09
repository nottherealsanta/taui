use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
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

#[derive(Clone, Debug)]
pub struct BackendClient {
    pub endpoint: String,
    request_id: Arc<Mutex<u64>>,
    #[allow(dead_code)]
    sender: Arc<Mutex<Option<mpsc::Sender<String>>>>,
}

impl BackendClient {
    pub fn new(endpoint: impl Into<String>) -> Self {
        Self {
            endpoint: endpoint.into(),
            request_id: Arc::new(Mutex::new(1)),
            sender: Arc::new(Mutex::new(None)),
        }
    }

    pub async fn connect(&self) -> Result<mpsc::Sender<String>> {
        let (ws_stream, _) = connect_async(&self.endpoint).await?;
        let (write, mut read) = ws_stream.split();

        let (tx, mut rx) = mpsc::channel::<String>(32);

        let write = Arc::new(Mutex::new(write));
        let write_clone = write.clone();

        tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                let mut writer = write_clone.lock().await;
                if writer.send(WsMessage::Text(msg)).await.is_err() {
                    break;
                }
            }
        });

        tokio::spawn(async move {
            while let Some(msg) = read.next().await {
                if let Ok(WsMessage::Text(text)) = msg {
                    println!("Received: {}", text);
                }
            }
        });

        Ok(tx)
    }

    async fn next_id(&self) -> u64 {
        let mut id = self.request_id.lock().await;
        let next = *id;
        *id += 1;
        next
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
        println!("Sending: {}", request_json);

        let (ws_stream, _) = connect_async(&self.endpoint).await?;
        let (mut write, mut read) = ws_stream.split();

        write.send(WsMessage::Text(request_json)).await?;

        while let Some(msg) = read.next().await {
            if let Ok(WsMessage::Text(text)) = msg {
                let response: JsonRpcResponse = serde_json::from_str(&text)?;

                if response.id == Some(id) {
                    if let Some(error) = response.error {
                        anyhow::bail!("RPC error {}: {}", error.code, error.message);
                    }
                    return response
                        .result
                        .ok_or_else(|| anyhow::anyhow!("No result in response"));
                }
            }
        }

        anyhow::bail!("No response received")
    }

    pub fn start_run(&self, spec_ref: &str) -> Result<RunId> {
        if spec_ref.trim().is_empty() {
            anyhow::bail!("spec_ref cannot be empty");
        }

        Ok(RunId(1))
    }
}
