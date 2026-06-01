"""Tests for MCP system — McpManager, McpClient, and McpTool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from taui.mcp import McpClient, McpManager, McpServerConfig
from taui.mcp import McpTool as McpToolInfo
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

    def test_load_global_self_edit_config(self, tmp_path: Path):
        config_dir = Path.home() / ".taui"
        config_dir.mkdir(parents=True)
        (config_dir / "mcp.toml").write_text(
            '[servers.global_demo]\ncommand = "echo"\nargs = ["hello"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert "global_demo" in mgr.server_names
        assert mgr._configs["global_demo"].command == ["echo", "hello"]

    def test_load_legacy_global_config(self, tmp_path: Path):
        config_dir = Path.home() / ".config" / "taui"
        config_dir.mkdir(parents=True)
        (config_dir / "mcp.toml").write_text(
            '[servers.legacy]\ncommand = ["echo", "legacy"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert "legacy" in mgr.server_names

    def test_project_config_overrides_global(self, tmp_path: Path):
        global_dir = Path.home() / ".taui"
        global_dir.mkdir(parents=True)
        (global_dir / "mcp.toml").write_text(
            '[servers.demo]\ncommand = ["echo", "global"]\n',
            encoding="utf-8",
        )
        project_dir = tmp_path / ".taui"
        project_dir.mkdir()
        (project_dir / "mcp.toml").write_text(
            '[servers.demo]\ncommand = ["echo", "project"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert mgr._configs["demo"].command == ["echo", "project"]

    def test_load_command_string_with_args(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        (config_dir / "mcp.toml").write_text(
            '[servers.demo]\ncommand = "echo"\nargs = ["hello"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()
        assert mgr._configs["demo"].command == ["echo", "hello"]

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

    async def test_reload_configs_disconnects_removed_server(self, tmp_path: Path):
        config_dir = tmp_path / ".taui"
        config_dir.mkdir()
        config_path = config_dir / "mcp.toml"
        config_path.write_text(
            '[servers.demo]\ncommand = ["echo", "hello"]\n',
            encoding="utf-8",
        )

        mgr = McpManager(tmp_path)
        mgr.load_configs()

        class FakeClient:
            def __init__(self, config: McpServerConfig) -> None:
                self.config = config
                self.disconnected = False

            @property
            def connected(self) -> bool:
                return not self.disconnected

            async def disconnect(self) -> None:
                self.disconnected = True

        client = FakeClient(mgr._configs["demo"])
        mgr._clients["demo"] = client

        config_path.write_text("", encoding="utf-8")
        await mgr.reload_configs()

        assert client.disconnected
        assert mgr.connected_servers == []


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
        self._fail_connect: bool = False  # when True, connect() always raises

    @property
    def server_names(self) -> list[str]:
        return sorted(self._configs)

    @property
    def connected_servers(self) -> list[str]:
        return [n for n, c in self._clients.items() if c.connected]

    async def connect(self, name: str) -> MockMcpClient:
        if name not in self._configs:
            raise ValueError(f"Unknown MCP server: {name!r}")
        cfg = self._configs[name]
        if not cfg.enabled:
            raise ValueError(f"MCP server '{name}' is disabled")
        if self._fail_connect:
            raise ConnectionError(f"mock failure for '{name}'")
        client = MockMcpClient(name)
        self._clients[name] = client
        return client

    async def connect_all(self) -> list[str]:
        connected: list[str] = []
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                continue
            if name in self._clients and self._clients[name].connected:
                connected.append(name)
                continue
            try:
                await self.connect(name)
                connected.append(name)
            except Exception:
                pass
        return connected

    def get_client(self, name: str) -> MockMcpClient | None:
        client = self._clients.get(name)
        if client and client.connected:
            return client
        return None

    def all_tools(self) -> list[McpToolInfo]:
        tools = []
        for client in self._clients.values():
            if client.connected:
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
    async def test_auto_connect_lists_tools(self):
        """tools auto-connects configured servers — no prior connect needed."""
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "tools"})
        assert not result.error
        assert "list_repos" in result.content
        assert "[github]" in result.content

    async def test_list_tools_already_connected(self):
        tool, mgr = _make_mcp_tool(["github"])
        await mgr.connect("github")
        result = await tool.execute({"operation": "tools"})
        assert not result.error
        assert "list_repos" in result.content
        assert "[github]" in result.content

    async def test_tools_specific_server(self):
        """tools with server arg auto-connects that server and lists only its tools."""
        tool, _ = _make_mcp_tool(["github", "filesystem"])
        result = await tool.execute({"operation": "tools", "server": "github"})
        assert not result.error
        assert "list_repos" in result.content
        assert "[github]" in result.content
        # Should not list the other server's tools header
        assert "[filesystem]" not in result.content

    async def test_tools_unknown_server(self):
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({"operation": "tools", "server": "nope"})
        assert result.error
        assert "Unknown" in result.content

    async def test_tools_no_servers_configured(self):
        """With no configured servers, shows 'no servers configured' message."""
        tool, _ = _make_mcp_tool()
        result = await tool.execute({"operation": "tools"})
        assert not result.error
        assert "No MCP servers configured" in result.content

    async def test_tools_all_connections_fail(self):
        """When all connect attempts fail, report the failure — not 'no tools'."""
        tool, mgr = _make_mcp_tool(["github"])
        mgr._fail_connect = True
        result = await tool.execute({"operation": "tools"})
        assert result.error
        assert "Failed to connect" in result.content

    async def test_tools_single_server_connect_fails(self):
        """Single-server tools request with connect failure."""
        tool, mgr = _make_mcp_tool(["github"])
        mgr._fail_connect = True
        result = await tool.execute({"operation": "tools", "server": "github"})
        assert result.error
        assert "Connection failed" in result.content


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

    async def test_call_auto_connect(self):
        """call with server+tool auto-connects — no prior connect needed."""
        tool, _ = _make_mcp_tool(["github"])
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

    async def test_call_auto_find_server_auto_connect(self):
        """call without server auto-connects all, then resolves tool name."""
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({
            "operation": "call",
            "tool": "list_repos",
        })
        assert not result.error
        assert "Called list_repos" in result.content

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

    async def test_call_unknown_server(self):
        """call with a truly unknown server still errors."""
        tool, _ = _make_mcp_tool(["github"])
        result = await tool.execute({
            "operation": "call",
            "server": "nope",
            "tool": "list_repos",
        })
        assert result.error
        assert "Unknown" in result.content


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


async def test_session_reload_mcp_configs_reloads_tool_manager(tmp_path: Path):
    from types import SimpleNamespace

    from taui.session import Session
    from taui.tools.registry import ToolRegistry

    registry = ToolRegistry()
    mcp_tool = McpTool()
    registry.register(mcp_tool)

    session = Session.__new__(Session)
    session.config = SimpleNamespace(working_dir=tmp_path)
    session._registry = registry
    session._config_change_listeners = []
    session._mcp_manager = McpManager(tmp_path)
    session._mcp_manager.load_configs()
    mcp_tool._manager = session._mcp_manager

    config_dir = tmp_path / ".taui"
    config_dir.mkdir()
    (config_dir / "mcp.toml").write_text(
        '[servers.demo]\ncommand = "echo"\nargs = ["hello"]\n',
        encoding="utf-8",
    )

    await session.reload_mcp_configs()

    assert mcp_tool._manager is session._mcp_manager
    assert session._mcp_manager.server_names == ["demo"]
