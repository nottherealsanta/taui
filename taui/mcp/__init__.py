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


@dataclass(slots=True)
class McpTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


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
            except (asyncio.TimeoutError, ProcessLookupError):
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
        except asyncio.TimeoutError:
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
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("MCP read loop error", exc_info=True)


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
