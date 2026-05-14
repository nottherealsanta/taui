"""Tests for MemoryTool."""


import pytest

from taui.tools.builtins.memory import MemoryTool


@pytest.fixture
def memory_tool(tmp_path):
    tool = MemoryTool()
    tool.working_dir = tmp_path
    return tool


class TestMemoryTool:
    def test_schema(self):
        tool = MemoryTool()
        assert tool.name == "memory"
        assert "operation" in tool.schema["required"]

    async def test_save_and_read(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "save",
            "key": "test-note",
            "content": "Important discovery.",
        })
        assert not result.error
        assert "Saved" in result.content

        result = await memory_tool.execute({
            "operation": "read",
            "key": "test-note",
        })
        assert not result.error
        assert result.content == "Important discovery."

    async def test_list_empty(self, memory_tool):
        result = await memory_tool.execute({"operation": "list"})
        assert not result.error
        assert "No memory entries" in result.content

    async def test_list_with_entries(self, memory_tool):
        await memory_tool.execute({
            "operation": "save", "key": "note-a", "content": "A",
        })
        await memory_tool.execute({
            "operation": "save", "key": "note-b", "content": "BB",
        })
        result = await memory_tool.execute({"operation": "list"})
        assert not result.error
        assert "note-a" in result.content
        assert "note-b" in result.content
        assert result.metadata["count"] == 2

    async def test_delete(self, memory_tool):
        await memory_tool.execute({
            "operation": "save", "key": "to-delete", "content": "Temp.",
        })
        result = await memory_tool.execute({
            "operation": "delete", "key": "to-delete",
        })
        assert not result.error
        assert "Deleted" in result.content

        # Verify it's gone
        result = await memory_tool.execute({
            "operation": "read", "key": "to-delete",
        })
        assert result.error

    async def test_read_nonexistent(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "read", "key": "nope",
        })
        assert result.error
        assert "not found" in result.content

    async def test_delete_nonexistent(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "delete", "key": "nope",
        })
        assert result.error

    async def test_unknown_operation(self, memory_tool):
        result = await memory_tool.execute({"operation": "merge"})
        assert result.error
        assert "Unknown operation" in result.content

    async def test_save_missing_key(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "save", "content": "No key.",
        })
        assert result.error

    async def test_save_missing_content(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "save", "key": "no-content",
        })
        assert result.error

    async def test_path_traversal_blocked(self, memory_tool):
        result = await memory_tool.execute({
            "operation": "save",
            "key": "../../etc/passwd",
            "content": "hax",
        })
        # Key gets sanitized — path traversal prevented
        assert not result.error  # Saves with sanitized key
        # Verify it didn't escape the memory dir
        evil_path = memory_tool.working_dir / ".." / ".." / "etc" / "passwd"
        assert not evil_path.exists()

    async def test_overwrite(self, memory_tool):
        await memory_tool.execute({
            "operation": "save", "key": "note", "content": "Version 1",
        })
        await memory_tool.execute({
            "operation": "save", "key": "note", "content": "Version 2",
        })
        result = await memory_tool.execute({
            "operation": "read", "key": "note",
        })
        assert result.content == "Version 2"
