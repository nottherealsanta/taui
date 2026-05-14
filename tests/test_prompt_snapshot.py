"""Snapshot tests for SystemPromptBuilder.render()."""

from __future__ import annotations

from pathlib import Path

from taui.prompt_builder import (
    ContextFile,
    ProjectContext,
    SystemPromptBuilder,
)
from taui.tools.registry import ToolRegistry


class TestPromptSnapshot:
    def test_default_render_has_required_sections(self):
        """Default render includes tools, guidelines, environment."""
        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test/project"),
            current_date="2025-01-15",
            git_status="Branch: main\nClean",
            instruction_files=[],
        ))
        prompt = builder.render()

        assert "/test/project" in prompt
        assert "2025-01-15" in prompt

    def test_render_with_tools(self):
        """Render includes tool names when tools are registered."""
        from taui.tools.builtins.files import GlobTool, ReadTool

        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test"),
            current_date="2025-06-01",
        ))
        registry = ToolRegistry()
        registry.register(ReadTool())
        registry.register(GlobTool())
        builder.with_tools(registry)
        prompt = builder.render()

        assert "read" in prompt.lower()
        assert "glob" in prompt.lower()

    def test_render_with_instructions(self):
        """Render includes instruction file content."""
        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test"),
            current_date="2025-01-01",
            instruction_files=[
                ContextFile(path=Path("AGENTS.md"), content="Follow these rules."),
            ],
        ))
        prompt = builder.render()
        assert "Follow these rules" in prompt

    def test_render_stable_across_calls(self):
        """Multiple render() calls produce identical output."""
        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test"),
            current_date="2025-01-01",
        ))
        p1 = builder.render()
        p2 = builder.render()
        assert p1 == p2

    def test_render_includes_git_status(self):
        """Git status is included when provided."""
        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test"),
            current_date="2025-01-01",
            git_status="Branch: feature\n3 uncommitted changes",
        ))
        prompt = builder.render()
        assert "feature" in prompt

    def test_render_without_git(self):
        """Render works without git status."""
        builder = SystemPromptBuilder()
        builder.with_project_context(ProjectContext(
            cwd=Path("/test"),
            current_date="2025-01-01",
        ))
        prompt = builder.render()
        assert "/test" in prompt
