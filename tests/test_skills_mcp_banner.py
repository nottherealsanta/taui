"""Tests for the SkillsBanner and McpBanner widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ── SkillsBanner ───────────────────────────────────────────────────────


@dataclass
class _FakeSkill:
    name: str
    scope: str = "global"
    content: str = ""
    loaded: bool = True
    path: Path = field(default_factory=lambda: Path("/fake/skills"))

    def load_content(self) -> str:
        return self.content


@dataclass
class _FakeSkillRegistry:
    skills: list[_FakeSkill] = field(default_factory=list)

    def list_all(self) -> list[_FakeSkill]:
        return list(self.skills)

    def loaded_skills(self) -> list[_FakeSkill]:
        return [s for s in self.skills if s.loaded]


def test_build_skills_payload_returns_all_discovered():
    from taui.tui.widgets.skills_banner import build_skills_payload

    reg = _FakeSkillRegistry(
        skills=[
            _FakeSkill(
                name="zed",
                scope="project",
                content="# Zed\n\nA Zed-related skill.\n",
                path=Path("/repo/.agents/skills/zed"),
            ),
            _FakeSkill(
                name="alpha",
                scope="global",
                content="Helps with alpha tasks.",
                loaded=True,
                path=Path("/home/u/.taui/skills/alpha"),
            ),
            _FakeSkill(
                name="unloaded",
                loaded=False,
                content="Not yet loaded.",
                path=Path("/home/u/.taui/skills/unloaded"),
            ),
        ],
    )
    payload = build_skills_payload(reg)
    names = [p[0] for p in payload]
    # Sorted alphabetically; unloaded skills are included.
    assert names == ["alpha", "unloaded", "zed"]
    by_name = {n: (s, p, d) for n, s, p, d in payload}
    assert by_name["alpha"] == (
        "global", "/home/u/.taui/skills/alpha", "Helps with alpha tasks.",
    )
    assert by_name["zed"] == (
        "project", "/repo/.agents/skills/zed", "A Zed-related skill.",
    )
    assert by_name["unloaded"] == (
        "global", "/home/u/.taui/skills/unloaded", "Not yet loaded.",
    )


def test_build_skills_payload_none_registry():
    from taui.tui.widgets.skills_banner import build_skills_payload

    assert build_skills_payload(None) == []


def test_skills_banner_has_label_and_body_and_hover_css():
    from taui.tui.widgets.skills_banner import SkillsBanner

    banner = SkillsBanner(
        [
            ("a", "global", "/path/to/a", ""),
            ("b", "global", "/path/to/b", ""),
        ],
        label_text=" Skills ",
        label_style="bold #fff on #8a8a8a",
    )
    assert " Skills " in banner._render_label()
    body = banner._render_body()
    assert "a" in body and "b" in body
    css = SkillsBanner.DEFAULT_CSS
    assert "SkillsBanner:hover" in css
    assert "background" in css


def test_skills_banner_empty_shows_placeholder():
    from taui.tui.widgets.skills_banner import SkillsBanner

    banner = SkillsBanner([])
    assert "no skills discovered" in banner._render_body()


# ── McpBanner ──────────────────────────────────────────────────────────


@dataclass
class _FakeMcpTool:
    name: str


@dataclass
class _FakeMcpClient:
    tools: list[_FakeMcpTool] = field(default_factory=list)


class _FakeMcpManager:
    def __init__(
        self,
        connected: list[str],
        all_servers: dict[str, list[str]],
    ) -> None:
        self.connected_servers = connected
        self._all_servers = all_servers
        self._clients = {
            name: _FakeMcpClient(tools=[_FakeMcpTool(t) for t in tools])
            for name, tools in all_servers.items()
        }

    @property
    def server_names(self) -> list[str]:
        return sorted(self._all_servers)

    def get_client(self, name: str):
        if name in self.connected_servers:
            return self._clients.get(name)
        return None


def test_build_mcp_payload_only_connected():
    from taui.tui.widgets.mcp_banner import build_mcp_payload

    mgr = _FakeMcpManager(
        connected=["github"],
        all_servers={
            "github": ["b_search", "a_clone"],
            "filesystem": ["read", "write"],  # not connected → omitted
        },
    )
    payload = build_mcp_payload(mgr)
    assert set(payload) == {"github"}
    assert payload["github"] == ["a_clone", "b_search"]  # sorted


def test_build_mcp_payload_none_manager():
    from taui.tui.widgets.mcp_banner import build_mcp_payload

    assert build_mcp_payload(None) == {}


def test_mcp_banner_has_label_and_body_and_hover_css():
    from taui.tui.widgets.mcp_banner import McpBanner

    banner = McpBanner(
        {"github": ["a", "b", "c"]},
        label_text=" MCP ",
        label_style="bold #fff on #8a8a8a",
    )
    assert " MCP " in banner._render_label()
    assert "github(3)" in banner._render_body()
    css = McpBanner.DEFAULT_CSS
    assert "McpBanner:hover" in css
    assert "background" in css


def test_mcp_banner_empty_shows_placeholder():
    from taui.tui.widgets.mcp_banner import McpBanner

    assert "no MCP servers connected" in McpBanner({})._render_body()


def test_mcp_modal_shows_unconnected_servers():
    """McpModal with mcp_manager lists configured-but-unconnected servers."""
    from taui.tui.widgets.mcp_banner import McpModal

    mgr = _FakeMcpManager(
        connected=["github"],
        all_servers={
            "github": ["search", "clone"],
            "filesystem": ["read", "write"],
        },
    )
    modal = McpModal({"github": ["clone", "search"]}, mcp_manager=mgr)
    infos = modal._all_server_info()
    names = [n for n, _, _ in infos]
    connected_flags = {n: c for n, c, _ in infos}
    assert "github" in names
    assert "filesystem" in names
    assert connected_flags["github"] is True
    assert connected_flags["filesystem"] is False


def test_mcp_modal_no_manager_falls_back():
    """McpModal without mcp_manager only shows the payload servers."""
    from taui.tui.widgets.mcp_banner import McpModal

    modal = McpModal({"github": ["a", "b"]})
    infos = modal._all_server_info()
    assert len(infos) == 1
    assert infos[0] == ("github", True, ["a", "b"])


def test_mcp_banner_passes_manager_to_modal():
    """McpBanner stores mcp_manager and passes it through."""
    from taui.tui.widgets.mcp_banner import McpBanner

    mgr = _FakeMcpManager(connected=[], all_servers={"x": []})
    banner = McpBanner({}, mcp_manager=mgr)
    assert banner._manager is mgr
