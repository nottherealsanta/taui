"""Tests for MCP system — McpManager, McpClient, and McpTool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from taui.mcp import McpClient, McpManager, McpServerConfig, McpTool as McpToolInfo
from taui.tools.builtins.mcp import McpTool


# ═══ McpServerConfig ══════════════════════════════════════════════════════════


class TestMcpServerConfig:
    def test_defaults(self):
        cfg = McpServerConfig(name="test", command=["echo"])
        assert cfg.enabled
        assert cfg.env == {}

    def test_with_env(self):
        cfg = McpServerConfig(
            name="github",
            command=["npx", "server-github"],
            env={"GITHUB_TOKEN": "abc"},
        )
        assert cfg.env["GITHUB_TOKEN"] == "abc"


# ═══ McpManager ═══════════════════════════════════════════════════════════════


class TestMcpManager:
    def test_empty_configs(self, tmp_path: Path):
        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert mgr.server_names == []

    def test_load_project_config(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        (config_dir / "mcp.toml").write_text(
            '[servers.myserver]\ncommand = ["echo", "hello"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert "myserver" in mgr.server_names

    def test_load_with_env(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        (config_dir / "mcp.toml").write_text(
            '[servers.gh]\ncommand = ["npx", "gh"]\n[servers.gh.env]\nTOKEN = "abc"\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert "gh" in mgr.server_names

    def test_load_invalid_config(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        (config_dir / "mcp.toml").write_text("not valid toml [[[", encoding="utf-8")

        mgr = McpManager(tmp_path)
        mgr.load_configs()  # Should not raise
        assert mgr.server_names == []

    def test_load_missing_command(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        (config_dir / "mcp.toml").write_text(
            '[servers.bad]\nenabled = true\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert mgr.server_names == []  # Skipped due to missing command

    def test_connected_servers_initially_empty(self, tmp_path: Path):
        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert mgr.connected_servers == []

    def test_all_tools_empty(self, tmp_path: Path):
        mgr = McpManager(tmp_path)
        assert mgr.all_tools() == []

    async def test_connect_unknown_server(self, tmp_path: Path):
        mgr = McpManager(tmp_path)
        mgr.load_configs()
        with pytest.raises(ValueError, match="Unknown"):
            await mgr.connect("nonexistent")


# ═══ McpClient ════════════════════════════════════════════════════════════════


class TestMcpClient:
    def test_not_connected_initially(self):
        cfg = McpServerConfig(name="test", command=["echo"])
        client = McpClient(cfg)
        assert not client.connected
        assert client.tools == []

    async def test_connect_missing_command(self):
        cfg = McpServerConfig(
            name="test",
            command=["__nonexistent_binary_12345__"],
        )
        client = McpClient(cfg)
        with pytest.raises(ConnectionError, match="not found"):
            await client.connect()


# ═══ McpTool ══════════════════════════════════════════════════════════════════


class MockMcpManager:
    """Mock MCP manager for testing the McpTool."""

    def __init__(self) -> None:
        self._configs: dict[str, McpServerConfig] = {}
        self._clients: dict[str, MockMcpClient] = {}

    @property
    def server_names(self) -> list[str]:
        return sorted(self._configs)

    @property
    def connected_servers(self) -> list[str]:
        return sorted(self._clients)

    async def connect(self, name: str) -> MockMcpClient:
        if name not in self._configs:
            raise ValueError(f"Unknown MCP server: {name!r}")
        client = MockMcpClient(name)
        self._clients[name] = client
        return client

    def get_client(self, name: str) -> MockMcpClient | None:
        return self._clients.get(name)

    def all_tools(self) -> list[McpToolInfo]:
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools


class MockMcpClient:
    """Mock MCP client."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._connected = True
        self._tools: list[McpToolInfo] = [
            McpToolInfo(
                name="list_repos",
                description="List repositories",
                input_schema={"type": "object", "properties": {}},
                server_name=name,
            ),
        ]
        self.call_results: dict[str, dict[str, Any]] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[McpToolInfo]:
        return list(self._tools)

    async def disconnect(self) -> None:
        self._connected = False

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if name in self.call_results:
            return self.call_results[name]
        return {
            "content": [{"type": "text", "text": f"Called {name} with {arguments}"}],
        }


def _make_mcp_tool(servers: list[str] | None = None) -> tuple[McpTool, MockMcpManager]:
    """Create McpTool with mock manager."""
    mgr = MockMcpManager()
    if servers:
        for name in servers:
            mgr._configs[name] = McpServerConfig(name=name, command=["echo"])

    tool = McpTool()
    tool._manager = mgr
    return tool, mgr


class TestMcpToolServers:
    async def test_no_servers(self):
        tool, _ = _make_mcp_tool()
        result = await tool.execute({"operation": "servers"})
        assert not result.error
        assert "No MCP servers" in result.content

    async def test_list_servers(self):
        tool, _ = _make_mcp_tool(["github", "filesystem"])
        result = await tool.execute({"operation": "servers"})
        assert not result.error
        assert "github" in result.content
        assert "filesystem" in result.content

    async def test_list_shows_connected_status(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({"operation": "servers"})
        assert "[connected]" in result.content


class TestMcpToolConnect:
    async def test_connect(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "connect", "server": "github"})
        assert not result.error
        assert "Connected" in result.content
        assert "list_repos" in result.content

    async def test_connect_unknown(self):
        tool, _ = _make_mcp_tool()
        result = await tool.execute({"operation": "connect", "server": "nope"})
        assert result.error

    async def test_connect_missing_name(self):
        tool, _ = _make_mcp_tool()
        result = await tool.execute({"operation": "connect"})
        assert result.error


class TestMcpToolDisconnect:
    async def test_disconnect(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({"operation": "disconnect", "server": "github"})
        assert not result.error
        assert "Disconnected" in result.content

    async def test_disconnect_not_connected(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "disconnect", "server": "github"})
        assert result.error


class TestMcpToolTools:
    async def test_no_connections(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "tools"})
        assert not result.error
        assert "No MCP servers connected" in result.content

    async def test_list_tools(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({"operation": "tools"})
        assert not result.error
        assert "list_repos" in result.content
        assert "[github]" in result.content


class TestMcpToolCall:
    async def test_call_tool(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({
            "operation": "call",
            "server": "github",
            "tool": "list_repos",
            "arguments": {"org": "test"},
        })
        assert not result.error
        assert "Called list_repos" in result.content

    async def test_call_auto_find_server(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({
            "operation": "call",
            "tool": "list_repos",
        })
        assert not result.error

    async def test_call_unknown_tool(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({
            "operation": "call",
            "tool": "nonexistent",
        })
        assert result.error
        assert "not found" in result.content

    async def test_call_missing_tool_name(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "call"})
        assert result.error

    async def test_call_error_response(self):
        tool, mgr = _make_mcp_tool(["github"])
        client = await mgr.connect("github")
        client.call_results["list_repos"] = {
            "content": [{"type": "text", "text": "rate limited"}],
            "isError": True,
        }
        result = await tool.execute({
            "operation": "call",
            "tool": "list_repos",
        })
        assert result.error
        assert "rate limited" in result.content

    async def test_call_server_not_connected(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({
            "operation": "call",
            "server": "github",
            "tool": "list_repos",
        })
        assert result.error
        assert "not connected" in result.content


class TestMcpToolErrors:
    async def test_no_manager(self):
        tool = McpTool()
        result = await tool.execute({"operation": "servers"})
        assert result.error
        assert "not configured" in result.content

    async def test_missing_operation(self):
        tool, _ = _make_mcp_tool()
        result = await tool.execute({})
        assert result.error

    async def test_unknown_operation(self):
        tool, _ = _make_mcp_tool()
        result = await tool.execute({"operation": "invalid"})
        assert result.error
