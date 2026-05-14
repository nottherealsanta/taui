"""
taui.mcp — Model Context Protocol client.

Connects to external MCP servers that expose tools and resources.
Each server is configured with a name, command to start it, and
optional environment variables.

MCP servers are discovered from:
    .taui/mcp.toml          — project-scoped
    ~/.config/taui/mcp.toml — global

Config format::

    [servers.filesystem]
    command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    [servers.github]
    command = ["npx", "-y", "@modelcontextprotocol/server-github"]
    env = { GITHUB_TOKEN = "..." }
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    transport: str = "stdio"
    prefix: str | None = None  # Override the default "mcp__<server>__" prefix

    def tool_prefix(self) -> str:
        """Return the prefix used to qualify tool names for this server.

        Falls back to ``mcp__<server>__`` when no custom prefix is set.
        """
        if self.prefix is not None:
            return self.prefix
        return f"mcp__{self.name}__"


@dataclass(slots=True)
class McpTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str

    @property
    def prefixed_name(self) -> str:
        """Return the default ``mcp__<server>__<name>`` qualified name."""
        return f"mcp__{self.server_name}__{self.name}"


class McpClient:
    """Client for a single MCP server using stdio JSON-RPC.

    Starts the server as a subprocess, communicates via stdin/stdout
    using the MCP JSON-RPC protocol (newline-delimited JSON).
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._tools: list[McpTool] = []
        self._reader_task: asyncio.Task | None = None
        self._sampling_handler: Callable | None = None

    @property
    def connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def connect(self) -> None:
        """Start the MCP server subprocess and initialize."""
        if self.connected:
            return

        import os

        env = {**os.environ, **self.config.env}
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            raise ConnectionError(
                f"MCP server command not found: {self.config.command[0]!r}"
            )
        except OSError as e:
            raise ConnectionError(f"Failed to start MCP server: {e}")

        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize
        result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "taui", "version": "0.1.0"},
        })
        if result is None:
            raise ConnectionError(
                f"MCP server '{self.config.name}' did not respond to initialize"
            )

        # Send initialized notification
        await self._notify("notifications/initialized", {})

        # List tools
        tools_result = await self._request("tools/list", {})
        if tools_result and "tools" in tools_result:
            self._tools = [
                McpTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self.config.name,
                )
                for t in tools_result["tools"]
            ]

    async def disconnect(self) -> None:
        """Stop the MCP server subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                self._process.kill()
            self._process = None
        # Cancel pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Server disconnected"))
        self._pending.clear()

    @property
    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        result = await self._request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            raise RuntimeError(f"No response from MCP server for tool '{name}'")
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        """List resources exposed by the MCP server."""
        result = await self._request("resources/list", {})
        if result and "resources" in result:
            return result["resources"]
        return []

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a specific resource by URI."""
        result = await self._request("resources/read", {"uri": uri})
        if result is None:
            raise RuntimeError(f"No response for resource '{uri}'")
        return result

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List prompt templates exposed by the MCP server."""
        result = await self._request("prompts/list", {})
        if result and "prompts" in result:
            return result["prompts"]
        return []

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Get a rendered prompt template."""
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        result = await self._request("prompts/get", params)
        if result is None:
            raise RuntimeError(f"No response for prompt '{name}'")
        return result

    async def _request(
        self, method: str, params: dict[str, Any], *, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for the response."""
        if not self.connected:
            raise ConnectionError("Not connected to MCP server")

        self._request_id += 1
        req_id = self._request_id

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            logger.warning("MCP request timed out: %s", method)
            return None

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.connected:
            return
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read responses from the MCP server stdout."""
        try:
            while self._process and self._process.returncode is None:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                req_id = msg.get("id")
                if req_id is not None and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if "error" in msg:
                        future.set_exception(
                            RuntimeError(
                                f"MCP error: {msg['error'].get('message', msg['error'])}"
                            )
                        )
                    elif not future.done():
                        future.set_result(msg.get("result", {}))

                # Handle sampling requests from server
                method = msg.get("method")
                if method == "sampling/createMessage":
                    req_id_server = msg.get("id")
                    if req_id_server is not None:
                        await self._handle_sampling(
                            req_id_server, msg.get("params", {})
                        )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("MCP read loop error", exc_info=True)

    async def _handle_sampling(
        self, req_id: int, params: dict[str, Any]
    ) -> None:
        """Handle a sampling/createMessage request from the server."""
        if self._sampling_handler:
            try:
                result = await self._sampling_handler(params)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
            except Exception as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": str(exc),
                    },
                }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": "Sampling not supported",
                },
            }
        data = json.dumps(response) + "\n"
        if self._process and self._process.stdin:
            self._process.stdin.write(data.encode())
            await self._process.stdin.drain()

    def set_sampling_handler(
        self, handler: Callable | None
    ) -> None:
        """Set a callback for sampling requests.

        handler(params: dict) -> dict with model response.
        """
        self._sampling_handler = handler


class McpHttpClient:
    """MCP client using HTTP/SSE transport.

    Connects to an MCP server via HTTP POST for requests and
    Server-Sent Events for notifications.
    """

    def __init__(self, base_url: str, *, name: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._name = name
        self._tools: list[McpTool] = []
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def connect(self) -> None:
        """Initialize connection and list tools."""
        result = await self._post("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "taui", "version": "0.4"},
        })
        if result is None:
            raise ConnectionError(
                f"MCP HTTP server at {self._base_url} did not respond"
            )

        await self._post("notifications/initialized", {}, notify=True)

        tools_result = await self._post("tools/list", {})
        if tools_result and "tools" in tools_result:
            self._tools = [
                McpTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self._name,
                )
                for t in tools_result["tools"]
            ]
        self._connected = True

    async def disconnect(self) -> None:
        """Mark as disconnected."""
        self._connected = False
        self._tools.clear()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool via HTTP POST."""
        result = await self._post("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            raise RuntimeError(f"No response for tool '{name}'")
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        result = await self._post("resources/list", {})
        if result and "resources" in result:
            return result["resources"]
        return []

    async def list_prompts(self) -> list[dict[str, Any]]:
        result = await self._post("prompts/list", {})
        if result and "prompts" in result:
            return result["prompts"]
        return []

    async def _post(
        self,
        method: str,
        params: dict[str, Any],
        *,
        notify: bool = False,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request via HTTP POST."""
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if not notify:
            msg["id"] = id(msg)

        url = f"{self._base_url}/rpc"
        data = json.dumps(msg).encode()

        def _do_request() -> bytes | None:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.URLError:
                return None

        try:
            raw = await asyncio.to_thread(_do_request)
        except Exception:
            return None

        if raw is None:
            return None
        if notify:
            return {}
        try:
            resp = json.loads(raw)
            return resp.get("result")
        except json.JSONDecodeError:
            return None


class McpManager:
    """Manages multiple MCP server connections.

    Discovers server configs from project and global config files,
    connects to enabled servers, and provides access to their tools.
    """

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._clients: dict[str, McpClient] = {}
        self._configs: dict[str, McpServerConfig] = {}

    def load_configs(self) -> None:
        """Load MCP server configs from config files."""
        self._configs.clear()

        # Global config
        global_path = Path.home() / ".config" / "taui" / "mcp.toml"
        self._load_config_file(global_path)

        # Project config (overrides global)
        project_path = self._working_dir / ".taui" / "mcp.toml"
        self._load_config_file(project_path)

    def _load_config_file(self, path: Path) -> None:
        """Load configs from a TOML file."""
        if not path.is_file():
            return
        try:
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
            servers = data.get("servers", {})
            for name, cfg in servers.items():
                command = cfg.get("command")
                if not command or not isinstance(command, list):
                    logger.warning("MCP server '%s': missing or invalid command", name)
                    continue
                self._configs[name] = McpServerConfig(
                    name=name,
                    command=command,
                    env=cfg.get("env", {}),
                    enabled=cfg.get("enabled", True),
                    transport=cfg.get("transport", "stdio"),
                    prefix=cfg.get("prefix"),
                )
        except Exception as e:
            logger.warning("Failed to load MCP config from %s: %s", path, e)

    @property
    def server_names(self) -> list[str]:
        return sorted(self._configs)

    @property
    def connected_servers(self) -> list[str]:
        return [n for n, c in self._clients.items() if c.connected]

    async def connect(self, name: str) -> McpClient:
        """Connect to a configured MCP server."""
        if name not in self._configs:
            raise ValueError(f"Unknown MCP server: {name!r}")

        cfg = self._configs[name]
        if not cfg.enabled:
            raise ValueError(f"MCP server '{name}' is disabled")

        if name in self._clients and self._clients[name].connected:
            return self._clients[name]

        client = McpClient(cfg)
        await client.connect()
        self._clients[name] = client
        return client

    async def connect_all(self) -> list[str]:
        """Connect to all enabled servers. Returns names of successfully connected."""
        connected: list[str] = []
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                continue
            try:
                await self.connect(name)
                connected.append(name)
            except Exception as e:
                logger.warning("Failed to connect MCP server '%s': %s", name, e)
        return connected

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                logger.debug("Error disconnecting MCP client", exc_info=True)
        self._clients.clear()

    def get_client(self, name: str) -> McpClient | None:
        """Get a connected client by name."""
        client = self._clients.get(name)
        if client and client.connected:
            return client
        return None

    def all_tools(self) -> list[McpTool]:
        """Get tools from all connected servers."""
        tools: list[McpTool] = []
        for client in self._clients.values():
            if client.connected:
                tools.extend(client.tools)
        return tools

    async def all_resources(self) -> list[dict[str, Any]]:
        """Get resources from all connected servers."""
        resources: list[dict[str, Any]] = []
        for name, client in self._clients.items():
            if client.connected:
                try:
                    server_resources = await client.list_resources()
                    for r in server_resources:
                        r["_server"] = name
                    resources.extend(server_resources)
                except Exception:
                    logger.debug(
                        "Failed listing resources from %s",
                        name, exc_info=True,
                    )
        return resources

    async def all_prompts(self) -> list[dict[str, Any]]:
        """Get prompt templates from all connected servers."""
        prompts: list[dict[str, Any]] = []
        for name, client in self._clients.items():
            if client.connected:
                try:
                    server_prompts = await client.list_prompts()
                    for p in server_prompts:
                        p["_server"] = name
                    prompts.extend(server_prompts)
                except Exception:
                    logger.debug(
                        "Failed listing prompts from %s",
                        name, exc_info=True,
                    )
        return prompts
