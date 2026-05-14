"""Tests for TaskTool."""
from __future__ import annotations

from pathlib import Path

from taui.tools.builtins.task import TaskTool


class TestTaskTool:
    async def test_list_empty(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        result = await tool.execute({"operation": "list"})
        assert not result.error
        assert "No tasks" in result.content

    async def test_add_task(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        result = await tool.execute({
            "operation": "add",
            "title": "Fix bug",
            "priority": "high",
        })
        assert not result.error
        assert "Fix bug" in result.content

    async def test_add_and_list(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        await tool.execute({"operation": "add", "title": "Task 1"})
        await tool.execute({"operation": "add", "title": "Task 2"})
        result = await tool.execute({"operation": "list"})
        assert "Task 1" in result.content
        assert "Task 2" in result.content

    async def test_complete_task(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        await tool.execute({"operation": "add", "title": "Do thing"})
        result = await tool.execute({"operation": "complete", "task_id": "1"})
        assert not result.error
        assert "completed" in result.content.lower()

    async def test_update_task(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        await tool.execute({"operation": "add", "title": "Old title"})
        result = await tool.execute({
            "operation": "update",
            "task_id": "1",
            "status": "in_progress",
            "priority": "high",
        })
        assert not result.error

    async def test_remove_task(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        await tool.execute({"operation": "add", "title": "Remove me"})
        result = await tool.execute({"operation": "remove", "task_id": "1"})
        assert not result.error
        list_result = await tool.execute({"operation": "list"})
        assert "No tasks" in list_result.content

    async def test_clear_tasks(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        await tool.execute({"operation": "add", "title": "Task"})
        result = await tool.execute({"operation": "clear"})
        assert not result.error

    async def test_add_without_title_fails(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        result = await tool.execute({"operation": "add"})
        assert result.error

    async def test_complete_nonexistent_fails(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        result = await tool.execute({"operation": "complete", "task_id": "999"})
        assert result.error

    async def test_unknown_operation(self, tmp_path: Path) -> None:
        tool = TaskTool()
        tool.working_dir = tmp_path
        tool._session_id = "test"
        result = await tool.execute({"operation": "unknown"})
        assert result.error
