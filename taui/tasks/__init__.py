"""Background task system — long-running sub-agents that don't block the main loop."""

from taui.tasks.manager import (
    BackgroundTask,
    TaskManager,
    TaskRecord,
    TaskState,
)

__all__ = [
    "BackgroundTask",
    "TaskManager",
    "TaskRecord",
    "TaskState",
]
