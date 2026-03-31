"""
Spec-tree agent tools — agent-facing tools that call SpecService methods.

All read operations are non-blocking. Write operations go through SpecService
which handles SQLite persistence and markdown writeback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult


def _ok(data: Any) -> ToolResult:
    return ToolResult.ok(json.dumps(data, default=str, indent=2))


def _fail(msg: str) -> ToolResult:
    return ToolResult.fail(msg)


def _get_spec_service(context: ToolContext) -> Any:
    """Extract SpecService from context.session (injected by AgentRunner)."""
    if context.session is None:
        raise RuntimeError("SpecService not available in tool context")
    svc = getattr(context.session, "spec_service", None)
    if svc is None:
        raise RuntimeError("SpecService not found in session")
    return svc


# ── spec_get_tree ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecGetTreeTool:
    name: str = "spec_get_tree"
    description: str = (
        "Read the full spec tree (all nodes). Returns a list of nodes with "
        "spec_ref, depth, and markdown content. Never blocked by locks."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "subtree_ref": {
                        "type": "string",
                        "description": "If provided, return only the subtree rooted at this spec_ref.",
                    }
                },
                "required": [],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        try:
            svc = _get_spec_service(context)
            nodes = await svc.get_tree()
            subtree_ref = arguments.get("subtree_ref")
            if subtree_ref:
                # Filter to the subtree
                # Find the target node depth and include all under it
                target = next((n for n in nodes if n.spec_ref == subtree_ref), None)
                if target is None:
                    return _fail(f"No node found for spec_ref: {subtree_ref!r}")
                # Simple: return all nodes at or under target's depth that share its prefix
                prefix = subtree_ref.split("#")[0]
                nodes = [
                    n
                    for n in nodes
                    if n.spec_ref == subtree_ref
                    or (
                        n.file_path.startswith(prefix.rstrip("/"))
                        and n.depth >= target.depth
                    )
                ]
            return _ok({"nodes": [n.to_dict() for n in nodes]})
        except Exception as exc:
            return _fail(f"spec_get_tree failed: {exc}")


# ── spec_get_node ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecGetNodeTool:
    name: str = "spec_get_node"
    description: str = (
        "Read a single spec node by its spec_ref. Returns full node detail "
        "including markdown content. Never blocked by locks."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node to read.",
                    }
                },
                "required": ["spec_ref"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        try:
            svc = _get_spec_service(context)
            node = await svc.get_node(spec_ref)
            return _ok({"node": node.to_dict()})
        except Exception as exc:
            return _fail(f"spec_get_node failed: {exc}")


# ── spec_get_branch ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecGetBranchTool:
    name: str = "spec_get_branch"
    description: str = (
        "Get the full subtree rooted at a given spec_ref. Returns the root node "
        "and all its descendants. Never blocked by locks."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the branch root node.",
                    }
                },
                "required": ["spec_ref"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        try:
            svc = _get_spec_service(context)
            root = await svc.get_node(spec_ref)
            subtree = await svc.db.get_subtree(root.id)
            all_nodes = [root] + subtree
            return _ok({"nodes": [n.to_dict() for n in all_nodes]})
        except Exception as exc:
            return _fail(f"spec_get_branch failed: {exc}")


# ── spec_update_node ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecUpdateNodeTool:
    name: str = "spec_update_node"
    description: str = (
        "Update the markdown content of a spec node. The node is identified by "
        "spec_ref. Returns the updated node."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node to update.",
                    },
                    "markdown": {
                        "type": "string",
                        "description": "New markdown content for the node.",
                    },
                },
                "required": ["spec_ref", "markdown"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        markdown = arguments.get("markdown")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        if not isinstance(markdown, str):
            return _fail("markdown must be a string")
        try:
            svc = _get_spec_service(context)
            result = await svc.update_node(spec_ref, {"markdown": markdown})
            return _ok(
                {
                    "node": result.node.to_dict(),
                    "previous_spec_ref": result.previous_spec_ref,
                }
            )
        except Exception as exc:
            return _fail(f"spec_update_node failed: {exc}")


# ── spec_create_sibling ────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecCreateSiblingTool:
    name: str = "spec_create_sibling"
    description: str = (
        "Create a new sibling node immediately after the given spec_ref node. "
        "The new node starts empty; use spec_update_node to set its content."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node to insert after.",
                    },
                },
                "required": ["spec_ref"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        try:
            svc = _get_spec_service(context)
            result = await svc.create_sibling_node(spec_ref)
            return _ok(
                {
                    "node": result.node.to_dict(),
                    "previous_spec_ref": result.previous_spec_ref,
                }
            )
        except Exception as exc:
            return _fail(f"spec_create_sibling failed: {exc}")


# ── spec_delete_node ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecDeleteNodeTool:
    name: str = "spec_delete_node"
    description: str = (
        "Delete a spec node (requires approval). "
        "This is a destructive operation — the node and its children will be removed."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node to delete.",
                    },
                },
                "required": ["spec_ref"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        try:
            svc = _get_spec_service(context)
            node = await svc.get_node(spec_ref)
            # Delete the node directly from DB
            await svc.db._execute("DELETE FROM nodes WHERE id = ?", (node.id,))
            await svc.db._conn.commit()
            return _ok({"deleted_spec_ref": spec_ref, "node_id": node.id})
        except Exception as exc:
            return _fail(f"spec_delete_node failed: {exc}")


# ── spec_move_node ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SpecMoveNodeTool:
    name: str = "spec_move_node"
    description: str = (
        "Reparent a spec node by indenting or outdenting it. "
        "Use 'indent' to make the node a child of its previous sibling, "
        "or 'outdent' to promote it one level up."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node to move.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["indent", "outdent"],
                        "description": "Whether to indent (make child) or outdent (promote).",
                    },
                },
                "required": ["spec_ref", "direction"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        direction = arguments.get("direction")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        if direction not in ("indent", "outdent"):
            return _fail("direction must be 'indent' or 'outdent'")
        try:
            svc = _get_spec_service(context)
            if direction == "indent":
                result = await svc.indent_node(spec_ref)
            else:
                result = await svc.outdent_node(spec_ref)
            return _ok(
                {
                    "node": result.node.to_dict(),
                    "previous_spec_ref": result.previous_spec_ref,
                }
            )
        except Exception as exc:
            return _fail(f"spec_move_node failed: {exc}")


# ── spec_ask_question ──────────────────────────────────────────────────────────


def _get_agent_runner(context: ToolContext) -> Any:
    """Extract AgentRunner from context.session (injected by AgentRunner)."""
    if context.session is None:
        raise RuntimeError("AgentRunner not available in tool context")
    runner = getattr(context.session, "agent_runner", None)
    if runner is None:
        raise RuntimeError("AgentRunner not found in session")
    return runner


@dataclass(slots=True)
class SpecAskQuestionTool:
    name: str = "spec_ask_question"
    description: str = (
        "Ask the user a question about the spec. The question is shown as an "
        "ephemeral overlay on the specified node in the UI. Blocks until the user "
        "answers or dismisses. Returns the user's answer, or null if dismissed."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SPEC

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "spec_ref": {
                        "type": "string",
                        "description": "The spec_ref of the node this question is about.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question text to show to the user.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of suggested answer choices.",
                    },
                },
                "required": ["spec_ref", "question"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spec_ref = arguments.get("spec_ref")
        question = arguments.get("question")
        options = arguments.get("options")
        if not isinstance(spec_ref, str) or not spec_ref.strip():
            return _fail("spec_ref must be a non-empty string")
        if not isinstance(question, str) or not question.strip():
            return _fail("question must be a non-empty string")
        if options is not None and not isinstance(options, list):
            return _fail("options must be a list of strings if provided")
        try:
            runner = _get_agent_runner(context)
            answer = await runner.ask_question(
                spec_ref=spec_ref,
                question=question,
                options=options,
            )
            return _ok({"answer": answer})
        except Exception as exc:
            return _fail(f"spec_ask_question failed: {exc}")


# ── Registry helper ────────────────────────────────────────────────────────────


def register_spec_tree_tools(registry: Any) -> None:
    """Register all spec-tree tools into a ToolRegistry."""
    for tool_cls in [
        SpecGetTreeTool,
        SpecGetNodeTool,
        SpecGetBranchTool,
        SpecUpdateNodeTool,
        SpecCreateSiblingTool,
        SpecDeleteNodeTool,
        SpecMoveNodeTool,
        SpecAskQuestionTool,
    ]:
        registry.register(tool_cls())
