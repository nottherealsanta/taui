"""Tests for the skill system — discovery, loading, and SkillsTool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from taui.skills import MAX_SKILL_CHARS, Skill, SkillRegistry
from taui.tools.builtins.skills import SkillsTool


# ═══ Skill dataclass ══════════════════════════════════════════════════════════


class TestSkill:
    def test_skill_file_path(self, tmp_path: Path):
        skill = Skill(name="test", path=tmp_path / "test", scope="project")
        assert skill.skill_file == tmp_path / "test" / "SKILL.md"

    def test_estimated_tokens_empty(self):
        skill = Skill(name="test", path=Path("."), scope="global")
        assert skill.estimated_tokens == 1  # min 1

    def test_estimated_tokens_with_content(self):
        skill = Skill(name="test", path=Path("."), scope="global", content="a" * 400)
        assert skill.estimated_tokens == 100  # 400 // 4

    def test_load_content(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill\n\nDo the thing.", encoding="utf-8")

        skill = Skill(name="my-skill", path=skill_dir, scope="project")
        content = skill.load_content()
        assert "# My Skill" in content
        assert "Do the thing" in content
        assert skill.content == content

    def test_load_content_cached(self, tmp_path: Path):
        skill_dir = tmp_path / "cached"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Original", encoding="utf-8")

        skill = Skill(name="cached", path=skill_dir, scope="project")
        skill.load_content()
        # Modify file — should not re-read (cached)
        (skill_dir / "SKILL.md").write_text("Modified", encoding="utf-8")
        assert skill.load_content() == "Original"

    def test_load_content_truncation(self, tmp_path: Path):
        skill_dir = tmp_path / "big"
        skill_dir.mkdir()
        big_content = "x" * (MAX_SKILL_CHARS + 1000)
        (skill_dir / "SKILL.md").write_text(big_content, encoding="utf-8")

        skill = Skill(name="big", path=skill_dir, scope="project")
        content = skill.load_content()
        assert len(content) < len(big_content)
        assert "[skill content truncated]" in content

    def test_load_content_missing_file(self, tmp_path: Path):
        skill = Skill(name="missing", path=tmp_path / "nonexistent", scope="project")
        content = skill.load_content()
        assert "Error reading skill" in content


# ═══ SkillRegistry ════════════════════════════════════════════════════════════


class TestSkillRegistry:
    def _setup_skills(self, tmp_path: Path, skills: dict[str, str]) -> Path:
        """Create skill directories with SKILL.md files."""
        skills_dir = tmp_path / ".taui" / "skills"
        for name, content in skills.items():
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return tmp_path

    def test_discover_empty(self, tmp_path: Path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_discover_project_skills(self, tmp_path: Path):
        self._setup_skills(tmp_path, {
            "testing": "# Testing Skill\nWrite tests.",
            "docker": "# Docker Skill\nUse containers.",
        })

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert sorted(reg.names) == ["docker", "testing"]

    def test_discover_scope(self, tmp_path: Path):
        self._setup_skills(tmp_path, {"myskill": "content"})

        reg = SkillRegistry(tmp_path)
        reg.discover()
        skill = reg.get("myskill")
        assert skill is not None
        assert skill.scope == "project"

    def test_discover_ignores_non_directories(self, tmp_path: Path):
        skills_dir = tmp_path / ".taui" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "not-a-skill.md").write_text("nope")

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_discover_ignores_dirs_without_skill_md(self, tmp_path: Path):
        skills_dir = tmp_path / ".taui" / "skills"
        (skills_dir / "incomplete").mkdir(parents=True)
        (skills_dir / "incomplete" / "README.md").write_text("not a skill file")

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.names == []

    def test_list_all(self, tmp_path: Path):
        self._setup_skills(tmp_path, {
            "alpha": "A",
            "beta": "B",
        })

        reg = SkillRegistry(tmp_path)
        reg.discover()
        all_skills = reg.list_all()
        assert len(all_skills) == 2
        assert [s.name for s in all_skills] == ["alpha", "beta"]

    def test_loaded_skills_initially_empty(self, tmp_path: Path):
        self._setup_skills(tmp_path, {"test": "content"})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.loaded_skills() == []

    def test_loaded_skills_after_marking(self, tmp_path: Path):
        self._setup_skills(tmp_path, {"test": "content"})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        reg.get("test").loaded = True
        loaded = reg.loaded_skills()
        assert len(loaded) == 1
        assert loaded[0].name == "test"

    def test_get_missing(self, tmp_path: Path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.get("nonexistent") is None

    def test_discover_agents_skills_dir(self, tmp_path: Path):
        """Skills in .agents/skills/ (Agent Skills standard) are discovered."""
        skills_dir = tmp_path / ".agents" / "skills" / "web-search"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Web Search", encoding="utf-8")

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert "web-search" in reg.names
        skill = reg.get("web-search")
        assert skill.scope == "project"

    def test_taui_skills_override_agents_skills(self, tmp_path: Path):
        """Skills in .taui/skills/ override same-named .agents/skills/."""
        # Create in .agents/skills/ first
        agents_dir = tmp_path / ".agents" / "skills" / "testing"
        agents_dir.mkdir(parents=True)
        (agents_dir / "SKILL.md").write_text("agents version", encoding="utf-8")

        # Create in .taui/skills/ (should override)
        taui_dir = tmp_path / ".taui" / "skills" / "testing"
        taui_dir.mkdir(parents=True)
        (taui_dir / "SKILL.md").write_text("taui version", encoding="utf-8")

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.names == ["testing"]
        skill = reg.get("testing")
        content = skill.load_content()
        assert "taui version" in content

    def test_discover_both_agents_and_taui(self, tmp_path: Path):
        """Skills from both .agents/skills/ and .taui/skills/ are found."""
        agents_dir = tmp_path / ".agents" / "skills" / "agent-skill"
        agents_dir.mkdir(parents=True)
        (agents_dir / "SKILL.md").write_text("from agents", encoding="utf-8")

        taui_dir = tmp_path / ".taui" / "skills" / "taui-skill"
        taui_dir.mkdir(parents=True)
        (taui_dir / "SKILL.md").write_text("from taui", encoding="utf-8")

        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert sorted(reg.names) == ["agent-skill", "taui-skill"]


# ═══ SkillsTool ═══════════════════════════════════════════════════════════════


def _make_skills_tool(tmp_path: Path, skills: dict[str, str] | None = None) -> SkillsTool:
    """Create a SkillsTool with a skill registry."""
    if skills:
        skills_dir = tmp_path / ".taui" / "skills"
        for name, content in skills.items():
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    reg = SkillRegistry(tmp_path)
    reg.discover()

    tool = SkillsTool()
    tool._skill_registry = reg
    return tool


class TestSkillsToolList:
    async def test_list_empty(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({"operation": "list"})
        assert not result.error
        assert "No skills found" in result.content

    async def test_list_skills(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {
            "testing": "# Testing\nWrite tests.",
            "docker": "# Docker\nContainers.",
        })
        result = await tool.execute({"operation": "list"})
        assert not result.error
        assert "testing" in result.content
        assert "docker" in result.content
        assert result.metadata["count"] == 2


class TestSkillsToolLoad:
    async def test_load_skill(self, tmp_path: Path):
        injected: list[str] = []

        async def capture_inject(content: str):
            injected.append(content)

        tool = _make_skills_tool(tmp_path, {"testing": "# Testing Skill\n\nWrite good tests."})
        tool._inject_message = capture_inject

        result = await tool.execute({"operation": "load", "skill": "testing"})
        assert not result.error
        assert "Loaded" in result.content
        assert result.metadata["skill"] == "testing"
        assert len(injected) == 1
        assert "Testing Skill" in injected[0]

    async def test_load_already_loaded(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {"testing": "content"})
        tool._skill_registry.get("testing").loaded = True

        result = await tool.execute({"operation": "load", "skill": "testing"})
        assert not result.error
        assert "already loaded" in result.content

    async def test_load_missing_skill(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({"operation": "load", "skill": "nonexistent"})
        assert result.error
        assert "not found" in result.content

    async def test_load_missing_skill_name(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({"operation": "load"})
        assert result.error

    async def test_load_without_inject_callback(self, tmp_path: Path):
        """Loading works even without inject callback (skill marked loaded)."""
        tool = _make_skills_tool(tmp_path, {"testing": "content"})
        # _inject_message is None by default
        result = await tool.execute({"operation": "load", "skill": "testing"})
        assert not result.error
        assert tool._skill_registry.get("testing").loaded


class TestSkillsToolUnload:
    async def test_unload_skill(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {"testing": "content"})
        tool._skill_registry.get("testing").loaded = True

        result = await tool.execute({"operation": "unload", "skill": "testing"})
        assert not result.error
        assert "Unloaded" in result.content
        assert not tool._skill_registry.get("testing").loaded

    async def test_unload_not_loaded(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {"testing": "content"})
        result = await tool.execute({"operation": "unload", "skill": "testing"})
        assert not result.error
        assert "not loaded" in result.content

    async def test_unload_missing(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({"operation": "unload", "skill": "nonexistent"})
        assert result.error


class TestSkillsToolStatus:
    async def test_status_none_loaded(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {"testing": "content"})
        result = await tool.execute({"operation": "status"})
        assert not result.error
        assert "No skills" in result.content

    async def test_status_with_loaded(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path, {"testing": "a" * 400, "docker": "b" * 200})
        tool._skill_registry.get("testing").loaded = True
        tool._skill_registry.get("testing").content = "a" * 400
        tool._skill_registry.get("docker").loaded = True
        tool._skill_registry.get("docker").content = "b" * 200

        result = await tool.execute({"operation": "status"})
        assert not result.error
        assert "testing" in result.content
        assert "docker" in result.content
        assert result.metadata["count"] == 2


class TestSkillsToolErrors:
    async def test_missing_operation(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({})
        assert result.error

    async def test_invalid_operation(self, tmp_path: Path):
        tool = _make_skills_tool(tmp_path)
        result = await tool.execute({"operation": "invalid"})
        assert result.error
        assert "Unknown operation" in result.content

    async def test_no_registry_configured(self):
        tool = SkillsTool()
        result = await tool.execute({"operation": "list"})
        assert result.error
        assert "not configured" in result.content
