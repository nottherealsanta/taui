"""Tests for the `/skills add` command path."""

from __future__ import annotations

from pathlib import Path

from taui.commands.builtins import SkillsCommand
from taui.commands.registry import CommandContext
from taui.skills import SkillRegistry


class _FakeSession:
    def __init__(self, reg: SkillRegistry) -> None:
        self._skill_registry = reg


def _make_command(tmp_path: Path) -> SkillsCommand:
    reg = SkillRegistry(tmp_path)
    reg.discover()
    cmd = SkillsCommand()
    cmd._get_session = lambda: _FakeSession(reg)
    return cmd


def _ctx(*args: str) -> CommandContext:
    return CommandContext(raw_input="/skills " + " ".join(args), args=list(args))


class TestSkillsAddCommand:
    async def test_add_returns_install_action(self, tmp_path: Path):
        cmd = _make_command(tmp_path)
        result = await cmd.execute(_ctx("add", "vercel-labs/agent-skills"))
        assert not result.error
        assert result.metadata["action"] == "skill_install"
        assert result.metadata["skill_source"] == "vercel-labs/agent-skills"

    async def test_add_joins_multiple_args(self, tmp_path: Path):
        cmd = _make_command(tmp_path)
        result = await cmd.execute(_ctx("add", "owner/repo", "-g"))
        assert result.metadata["skill_source"] == "owner/repo -g"

    async def test_add_without_source_fails(self, tmp_path: Path):
        cmd = _make_command(tmp_path)
        result = await cmd.execute(_ctx("add"))
        assert result.error
        assert "Usage" in result.output

    async def test_bare_name_still_toggles(self, tmp_path: Path):
        # A known skill name (not "add") routes to skill_selected as before.
        skill_dir = tmp_path / ".taui" / "skills" / "mine"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Mine", encoding="utf-8")
        cmd = _make_command(tmp_path)
        result = await cmd.execute(_ctx("mine"))
        assert result.metadata["action"] == "skill_selected"
        assert result.metadata["skill_name"] == "mine"
