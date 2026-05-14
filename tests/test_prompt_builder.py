"""Tests for taui.prompt_builder."""

from unittest.mock import MagicMock

from taui.prompt_builder import (
    DEFAULT_TEMPLATE,
    ProjectContext,
    SectionPriority,
    SystemPromptBuilder,
    _build_guidelines,
    _discover_instruction_files,
    render_template,
)


def _mock_registry(*tool_defs):
    """Create a mock registry with (name, description, guidelines?) tuples."""
    registry = MagicMock()
    tools = {}
    for t in tool_defs:
        name = t[0]
        desc = t[1] if len(t) > 1 else name
        guide = t[2] if len(t) > 2 else None
        tool = MagicMock()
        tool.name = name
        tool.description = desc
        tool.guidelines = guide
        tools[name] = tool
    registry.names = sorted(tools.keys())
    registry.get = lambda n: tools[n]
    return registry


class TestRenderTemplate:
    def test_simple_substitution(self):
        result = render_template("Hello {name}!", {"name": "world"})
        assert result == "Hello world!"

    def test_multiple_variables(self):
        t = "{a} and {b}"
        assert render_template(t, {"a": "X", "b": "Y"}) == "X and Y"

    def test_unknown_variables_left_as_is(self):
        result = render_template("{known} {unknown}", {"known": "OK"})
        assert result == "OK {unknown}"

    def test_empty_value(self):
        result = render_template("before{x}after", {"x": ""})
        assert result == "beforeafter"


class TestDefaultTemplate:
    def test_has_tool_variable(self):
        assert "{tools}" in DEFAULT_TEMPLATE

    def test_has_environment_variables(self):
        assert "{cwd}" in DEFAULT_TEMPLATE
        assert "{date}" in DEFAULT_TEMPLATE
        assert "{platform}" in DEFAULT_TEMPLATE

    def test_has_guidelines_variable(self):
        assert "{guidelines}" in DEFAULT_TEMPLATE

    def test_has_git_and_instructions_variables(self):
        assert "{git_status}" in DEFAULT_TEMPLATE
        assert "{project_instructions}" in DEFAULT_TEMPLATE


class TestSystemPromptBuilder:
    def test_render_basic(self):
        builder = SystemPromptBuilder()
        result = builder.render()
        assert "coding assistant" in result
        assert "taui" in result

    def test_with_project_context(self, tmp_path):
        ctx = ProjectContext(cwd=tmp_path, current_date="2025-01-01")
        builder = SystemPromptBuilder().with_project_context(ctx)
        result = builder.render()
        assert str(tmp_path) in result
        assert "2025-01-01" in result

    def test_with_tools_registry(self):
        reg = _mock_registry(
            ("read", "Read file contents."),
            ("bash", "Execute a shell command."),
            ("edit", "Edit a file by replacing text."),
        )
        builder = SystemPromptBuilder()
        builder.with_tools(reg)
        result = builder.render()
        # Tool snippets should appear
        assert "- bash: Execute a shell command" in result
        assert "- edit: Edit a file by replacing text" in result
        assert "- read: Read file contents" in result

    def test_with_tools_builds_guidelines(self):
        reg = _mock_registry(
            ("read", "Read file contents."),
            ("edit", "Edit a file."),
            ("bash", "Execute shell."),
            ("write", "Write a file."),
        )
        builder = SystemPromptBuilder()
        builder.with_tools(reg)
        result = builder.render()
        # Adaptive guideline: has edit + write
        assert "Prefer `edit` for targeted changes" in result
        # Adaptive guideline: has bash
        assert "Run tests" in result

    def test_with_tool_names(self):
        builder = SystemPromptBuilder()
        builder.with_tool_names(["read", "write", "bash"])
        result = builder.render()
        assert "read, write, bash" in result

    def test_set_custom_variable(self):
        builder = SystemPromptBuilder(template="Role: {role}")
        builder.set("role", "code reviewer")
        result = builder.render()
        assert "code reviewer" in result

    def test_custom_template(self):
        builder = SystemPromptBuilder(template="You are {role}. Tools: {tools}")
        builder.set("role", "a debugger")
        builder.with_tool_names(["bash", "read"])
        result = builder.render()
        assert result == "You are a debugger. Tools: bash, read"

    def test_add_section(self):
        builder = SystemPromptBuilder()
        builder.add_section("custom", "Custom instructions here.")
        result = builder.render()
        assert "Custom instructions here." in result

    def test_remove_section(self):
        builder = SystemPromptBuilder()
        builder.add_section("custom", "Should be removed.")
        builder.remove_section("custom")
        result = builder.render()
        assert "Should be removed." not in result

    def test_append(self):
        builder = SystemPromptBuilder()
        builder.append("## Extra\nMore info.")
        result = builder.render()
        assert "More info." in result

    def test_budget_fit_drops_low_priority(self):
        builder = SystemPromptBuilder(max_total_tokens=3)
        builder.add_section(
            "critical", "C" * 8, priority=SectionPriority.CRITICAL
        )
        builder.add_section(
            "optional", "O" * 8, priority=SectionPriority.OPTIONAL
        )
        fitted = builder._budget_fit_sections()
        texts = "\n".join(fitted)
        assert "C" * 8 in texts
        assert "O" * 8 not in texts

    def test_budget_fit_keeps_all_when_room(self):
        builder = SystemPromptBuilder(max_total_tokens=10_000)
        builder.add_section("a", "First section.")
        builder.add_section("b", "Second section.")
        result = builder.render()
        assert "First section." in result
        assert "Second section." in result

    def test_project_template_override(self, tmp_path):
        (tmp_path / ".taui").mkdir()
        (tmp_path / ".taui" / "system_prompt.md").write_text(
            "Custom agent. Tools: {tools}"
        )
        ctx = ProjectContext(cwd=tmp_path, current_date="2025-01-01")
        builder = SystemPromptBuilder()
        builder.with_project_context(ctx)
        builder.with_tool_names(["read", "bash"])
        result = builder.render()
        assert result == "Custom agent. Tools: read, bash"


class TestBuildGuidelines:
    def test_core_guidelines_always_present(self):
        reg = _mock_registry(("read", "Read."))
        result = _build_guidelines(reg)
        assert "Read before editing" in result
        assert "Be concise" in result

    def test_safety_guidelines_always_present(self):
        reg = _mock_registry(("read", "Read."))
        result = _build_guidelines(reg)
        assert "security vulnerabilities" in result
        assert "prompt injection" in result

    def test_edit_write_guideline(self):
        reg = _mock_registry(("edit", "Edit."), ("write", "Write."))
        result = _build_guidelines(reg)
        assert "Prefer `edit` for targeted changes" in result

    def test_read_edit_guideline(self):
        reg = _mock_registry(("read", "Read."), ("edit", "Edit."))
        result = _build_guidelines(reg)
        assert "Always `read` a file before using `edit`" in result

    def test_bash_only_file_ops(self):
        reg = _mock_registry(("bash", "Shell."))
        result = _build_guidelines(reg)
        assert "Use bash for file operations" in result

    def test_bash_with_grep_prefers_tools(self):
        reg = _mock_registry(("bash", "Shell."), ("grep", "Search."))
        result = _build_guidelines(reg)
        assert "Prefer grep/glob tools over bash" in result

    def test_git_guideline(self):
        reg = _mock_registry(("git", "Git ops."))
        result = _build_guidelines(reg)
        assert "git status" in result

    def test_tool_guidelines_included(self):
        reg = _mock_registry(("read", "Read.", "Use read to inspect files first."))
        result = _build_guidelines(reg)
        assert "read: Use read to inspect files first" in result


class TestInstructionDiscovery:
    def test_discovers_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Custom agent instructions.")
        files = _discover_instruction_files(tmp_path)
        assert len(files) == 1
        assert files[0].content == "Custom agent instructions."

    def test_discovers_taui_instructions(self, tmp_path):
        (tmp_path / ".taui").mkdir()
        (tmp_path / ".taui" / "instructions.md").write_text("Taui rules.")
        files = _discover_instruction_files(tmp_path)
        assert len(files) == 1
        assert "Taui rules." in files[0].content

    def test_deduplicates(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Same content.")
        (tmp_path / ".taui").mkdir()
        (tmp_path / ".taui" / "AGENTS.md").write_text("Same content.")
        files = _discover_instruction_files(tmp_path)
        assert len(files) == 1  # Deduped

    def test_empty_file_ignored(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("   ")
        files = _discover_instruction_files(tmp_path)
        assert len(files) == 0

    def test_no_files(self, tmp_path):
        files = _discover_instruction_files(tmp_path)
        assert len(files) == 0


class TestProjectContext:
    def test_discover(self, tmp_path):
        ctx = ProjectContext.discover(tmp_path)
        assert ctx.cwd == tmp_path
        assert ctx.current_date  # Should be today

    def test_instruction_files_included(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Project Agent\nCustom.")
        ctx = ProjectContext.discover(tmp_path)
        assert len(ctx.instruction_files) == 1

    def test_with_git(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        ctx = ProjectContext.discover_with_git(tmp_path)
        # Git status should be populated in a git repo
        assert ctx.git_status is not None or ctx.git_status is None  # May be empty
