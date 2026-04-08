"""TaskGraph — maps spec nodes to executable tasks with dependency ordering.

Inspired by claw-code's execution planning: the TaskGraph walks the spec
tree and produces a dependency-ordered plan of tasks that agents can
execute.  Each task corresponds to a spec node (or sub-tree) and carries
metadata about what needs to be done, its dependencies, and its current
status.

Usage::

    graph = TaskGraph.from_spec_nodes(nodes)
    ready = graph.ready_tasks()       # no unmet dependencies
    graph.mark_done("feature/auth")
    next_batch = graph.ready_tasks()  # newly unblocked tasks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class TaskNode:
    """A single executable task derived from a spec node."""

    spec_ref: str
    title: str
    depth: int
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    agent_id: str | None = None  # assigned agent
    error: str | None = None

    # Extracted from spec node
    markdown: str = ""
    code_refs: list[str] = field(default_factory=list)
    verification: str | None = None

    def is_leaf(self) -> bool:
        """Leaf tasks have no children in the graph."""
        return True  # overridden by TaskGraph

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_ref": self.spec_ref,
            "title": self.title,
            "depth": self.depth,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "agent_id": self.agent_id,
            "error": self.error,
            "verification": self.verification,
        }


class TaskGraph:
    """Dependency-ordered task graph built from spec nodes.

    Provides topological ordering, ready-task queries, and status
    tracking.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskNode] = {}
        self._children: dict[str, list[str]] = {}  # parent → children

    @classmethod
    def from_spec_nodes(cls, nodes: list[Any]) -> "TaskGraph":
        """Build a TaskGraph from a list of SpecNode objects.

        Nodes are included as tasks.  Dependencies come from the node's
        ``depends_on`` field.  Parent-child relationships are inferred
        from spec_ref hierarchy (e.g. ``a/b`` is child of ``a``).
        """
        graph = cls()

        for node in nodes:
            title = ""
            if node.markdown:
                first_line = node.markdown.split("\n")[0].lstrip("# ").strip()
                title = first_line or node.anchor
            else:
                title = node.anchor

            task = TaskNode(
                spec_ref=node.spec_ref,
                title=title,
                depth=node.depth,
                depends_on=list(node.depends_on) if node.depends_on else [],
                markdown=node.markdown or "",
                code_refs=list(node.code_refs) if node.code_refs else [],
                verification=node.verification,
            )

            # Map existing status
            if node.status == "done":
                task.status = TaskStatus.DONE
            elif node.status == "in_progress":
                task.status = TaskStatus.IN_PROGRESS
            elif node.status == "skipped":
                task.status = TaskStatus.SKIPPED

            graph._tasks[node.spec_ref] = task

        # Build parent-child index
        graph._rebuild_children_index()

        # Mark ready tasks
        graph._update_readiness()

        return graph

    def _rebuild_children_index(self) -> None:
        """Infer parent-child from spec_ref hierarchy."""
        self._children.clear()
        refs = sorted(self._tasks.keys())
        for ref in refs:
            # Find parent: longest prefix that is also a task
            parts = ref.rsplit("/", 1)
            if len(parts) == 2:
                parent_ref = parts[0]
                if parent_ref in self._tasks:
                    self._children.setdefault(parent_ref, []).append(ref)

    def _update_readiness(self) -> None:
        """Mark PENDING tasks as READY if all dependencies are met."""
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if self._deps_met(task):
                task.status = TaskStatus.READY

    def _deps_met(self, task: TaskNode) -> bool:
        """Check if all explicit dependencies are DONE or SKIPPED."""
        for dep_ref in task.depends_on:
            dep = self._tasks.get(dep_ref)
            if dep is None:
                continue  # external dependency — assume met
            if dep.status not in (TaskStatus.DONE, TaskStatus.SKIPPED):
                return False
        return True

    # ── Queries ────────────────────────────────────────────────────────

    def get(self, spec_ref: str) -> TaskNode | None:
        return self._tasks.get(spec_ref)

    def all_tasks(self) -> list[TaskNode]:
        return list(self._tasks.values())

    def ready_tasks(self) -> list[TaskNode]:
        """Return tasks that are ready to execute (deps met, not started)."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.READY]

    def leaf_tasks(self) -> list[TaskNode]:
        """Return tasks with no children."""
        parent_refs = set(self._children.keys())
        return [t for t in self._tasks.values() if t.spec_ref not in parent_refs]

    def children_of(self, spec_ref: str) -> list[TaskNode]:
        """Return direct children of a task."""
        child_refs = self._children.get(spec_ref, [])
        return [self._tasks[r] for r in child_refs if r in self._tasks]

    def topological_order(self) -> list[TaskNode]:
        """Return tasks in dependency order (dependencies before dependents)."""
        visited: set[str] = set()
        result: list[TaskNode] = []

        def visit(ref: str) -> None:
            if ref in visited:
                return
            visited.add(ref)
            task = self._tasks.get(ref)
            if task is None:
                return
            for dep in task.depends_on:
                visit(dep)
            result.append(task)

        for ref in self._tasks:
            visit(ref)

        return result

    # ── Mutations ──────────────────────────────────────────────────────

    def mark_in_progress(self, spec_ref: str, agent_id: str | None = None) -> bool:
        task = self._tasks.get(spec_ref)
        if task is None:
            return False
        task.status = TaskStatus.IN_PROGRESS
        task.agent_id = agent_id
        return True

    def mark_done(self, spec_ref: str) -> bool:
        task = self._tasks.get(spec_ref)
        if task is None:
            return False
        task.status = TaskStatus.DONE
        self._update_readiness()
        return True

    def mark_failed(self, spec_ref: str, error: str = "") -> bool:
        task = self._tasks.get(spec_ref)
        if task is None:
            return False
        task.status = TaskStatus.FAILED
        task.error = error
        return True

    def mark_skipped(self, spec_ref: str) -> bool:
        task = self._tasks.get(spec_ref)
        if task is None:
            return False
        task.status = TaskStatus.SKIPPED
        self._update_readiness()
        return True

    # ── Summary ────────────────────────────────────────────────────────

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        counts["total"] = len(self._tasks)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "tasks": [t.to_dict() for t in self.topological_order()],
        }
