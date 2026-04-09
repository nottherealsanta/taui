from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Callable

from taui.config.project_settings import ProjectSettingsStore
from taui.tangle import (
    SpecNodePatch,
    SpecService,
    SpecServiceError,
    SpecValidationError,
)
from taui.tangle.agent_db import AgentHistoryDB
from taui.agent.manager import AgentManager
from taui.tangle.history_store import ProjectHistoryStore

from .protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    SPEC_SERVICE_ERROR,
    JsonRpcProtocolError,
    JsonRpcRequest,
    notification_message,
)
from .state import RunState, RunProcess

logger = logging.getLogger(__name__)

CODE_REF_RANGE_RE = re.compile(r"^L(?P<start>\d+)(?:-L?(?P<end>\d+))?$", re.IGNORECASE)


NotificationCallback = Callable[[dict[str, Any]], None]


def _with_tangle_ref(node: dict[str, Any]) -> dict[str, Any]:
    out = dict(node)
    if "tangle_ref" not in out and "spec_ref" in out:
        out["tangle_ref"] = out["spec_ref"]
    return out


class _NoOpLLMClient:
    """Stub LLM client that immediately finishes with no tool calls.

    Used when no real LLM provider is configured (e.g. in tests or when
    credentials are unavailable).
    """

    async def create_turn(
        self,
        messages: list[Any],
        model: str,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        from taui.llms.base import ProviderTurnResult

        return ProviderTurnResult(
            response_id=None,
            text="Task complete (no-op).",
            tool_calls=[],
        )


@dataclass(slots=True)
class DispatchResult:
    result: dict[str, Any] | None
    notifications: list[dict[str, Any]]


class MethodHandlers:
    def __init__(
        self,
        workspace: Path | str | None = None,
        tangles_path: Path | str | None = None,
        specs_path: Path | str | None = None,
        dev_mode: bool = False,
        history_db_path: Path | str | None = None,
    ) -> None:
        self.tangles = SpecService(
            workspace=workspace,
            tangles_path=tangles_path,
            specs_path=specs_path,
            dev_mode=dev_mode,
        )
        self.specs = self.tangles
        self.workspace = self.tangles.workspace
        self.settings = ProjectSettingsStore(self.workspace)
        self.run_state = RunState()
        self._notification_callback: NotificationCallback | None = None
        workspace_path = Path(workspace).resolve() if workspace else None
        self.agent_db = AgentHistoryDB(self.tangles.workspace)
        self.history_db = ProjectHistoryStore(self.agent_db)
        self.agent_manager = AgentManager(
            db=self.agent_db,
            history_db=self.history_db,
            workspace=workspace_path,
        )
        self._prime_agent: Any | None = None  # Lazily created PrimeAgent
        self._symbol_indexer: Any | None = None
        self._symbol_resolver: Any | None = None
        self._symbol_db: Any | None = None

    async def _ensure_tangles(self) -> None:
        await self.tangles.ensure_initialized()

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        self._notification_callback = callback
        self.agent_manager.set_notification_callback(callback)

    async def drain_notifications(self) -> None:
        return

    def _emit_notification(self, notification: dict[str, Any]) -> None:
        if self._notification_callback:
            self._notification_callback(notification)

    async def dispatch(self, request: JsonRpcRequest) -> DispatchResult:
        method = request.method
        params = request.params
        started = time.perf_counter()
        logger.info(
            "RPC → method=%s request_id=%s",
            method,
            request.request_id,
        )

        try:
            if method == "initialize":
                return DispatchResult(
                    result=self._handle_initialize(params), notifications=[]
                )
            if method == "shutdown":
                return DispatchResult(result={"ok": True}, notifications=[])
            if method == "exit":
                return DispatchResult(result=None, notifications=[])
            if method == "tangle/getTree":
                return DispatchResult(
                    result=await self._handle_spec_get_tree(), notifications=[]
                )
            if method == "tangle/getTreeDetailed":
                return DispatchResult(
                    result=await self._handle_spec_get_tree_detailed(), notifications=[]
                )
            if method == "tangle/getNode":
                return DispatchResult(
                    result=await self._handle_spec_get_node(params), notifications=[]
                )
            if method == "tangle/updateNode":
                return await self._handle_spec_update_node(params)
            if method == "tangle/createSiblingNode":
                return await self._handle_spec_create_sibling_node(params)
            if method == "tangle/indentNode":
                return await self._handle_spec_indent_node(params)
            if method == "tangle/outdentNode":
                return await self._handle_spec_outdent_node(params)
            if method == "tangle/getNodeSourceRange":
                return DispatchResult(
                    result=await self._handle_spec_get_node_source_range(params),
                    notifications=[],
                )
            if method == "tangle/getNodeCodeRefs":
                return DispatchResult(
                    result=await self._handle_spec_get_node_code_refs(params),
                    notifications=[],
                )
            if method == "tangle/setNodeCollapsed":
                return DispatchResult(
                    result=await self._handle_spec_set_node_collapsed(params),
                    notifications=[],
                )
            if method == "run/start":
                return await self._handle_run_start(params)
            if method == "run/stop":
                return await self._handle_run_stop()
            if method == "run/status":
                return DispatchResult(result=self.run_state.to_dict(), notifications=[])
            if method == "prime/message":
                return await self._handle_prime_message(params)
            if method == "prime/newContext":
                return await self._handle_prime_new_context(params)
            if method == "prime/cancel":
                return await self._handle_prime_cancel()
            if method == "prime/history":
                return await self._handle_prime_history(params)
            if method == "agent/launch":
                return await self._handle_agent_launch(params)
            if method == "agent/stop":
                return await self._handle_agent_stop(params)
            if method == "agent/close":
                return await self._handle_agent_close(params)
            if method == "agent/list":
                return await self._handle_agent_list()
            if method == "agent/steer":
                return await self._handle_agent_steer(params)
            if method == "agent/queue":
                return await self._handle_agent_queue(params)
            if method == "agent/subscribe":
                return await self._handle_agent_subscribe(params)
            if method == "agent/unsubscribe":
                return await self._handle_agent_unsubscribe(params)
            if method == "agent/answerQuestion":
                return await self._handle_agent_answer_question(params)
            if method == "ui/snapshot":
                return await self._handle_ui_snapshot()
            if method == "ui/openTab":
                return await self._handle_ui_open_tab(params)
            if method == "ui/closeTab":
                return await self._handle_ui_close_tab(params)
            if method == "ui/setActiveTab":
                return await self._handle_ui_set_active_tab(params)
            if method == "ui/updateLayout":
                return await self._handle_ui_update_layout(params)
            if method == "ui/setTheme":
                return await self._handle_ui_set_theme(params)
            if method == "ui/saveTab":
                return await self._handle_ui_save_tab(params)
            if method == "ui/nodeEdited":
                return await self._handle_ui_node_edited(params)
            if method == "fs/listDir":
                return DispatchResult(
                    result=await self._handle_fs_list_dir(params),
                    notifications=[],
                )
            if method == "fs/readFile":
                return DispatchResult(
                    result=await self._handle_fs_read_file(params),
                    notifications=[],
                )
            if method == "fs/writeFile":
                return DispatchResult(
                    result=await self._handle_fs_write_file(params),
                    notifications=[],
                )
            if method == "fs/createDir":
                return DispatchResult(
                    result=await self._handle_fs_create_dir(params),
                    notifications=[],
                )
            if method == "fs/search":
                return DispatchResult(
                    result=await self._handle_fs_search(params),
                    notifications=[],
                )
            if method == "tangle/getBacklinks":
                return DispatchResult(
                    result=await self._handle_spec_get_backlinks(params),
                    notifications=[],
                )
            if method == "prompts/list":
                return await self._handle_prompts_list()
            if method == "prompts/get":
                return await self._handle_prompts_get(params)
            if method == "prompts/update":
                return await self._handle_prompts_update(params)
            if method == "prompts/reset":
                return await self._handle_prompts_reset(params)
            if method == "refs/search":
                return DispatchResult(
                    result=await self._handle_refs_search(params),
                    notifications=[],
                )
            if method == "refs/resolve":
                return DispatchResult(
                    result=await self._handle_refs_resolve(params),
                    notifications=[],
                )
            if method == "refs/getDefinition":
                return DispatchResult(
                    result=await self._handle_refs_get_definition(params),
                    notifications=[],
                )
            if method == "refs/updateValue":
                return DispatchResult(
                    result=await self._handle_refs_update_value(params),
                    notifications=[],
                )
            if method == "refs/backlinks":
                return DispatchResult(
                    result=await self._handle_refs_backlinks(params),
                    notifications=[],
                )
            if method == "refs/validate":
                return DispatchResult(
                    result=await self._handle_refs_validate(params),
                    notifications=[],
                )
            if method == "refs/reindex":
                return DispatchResult(
                    result=await self._handle_refs_reindex(params),
                    notifications=[],
                )
            logger.warning(
                "Unknown method=%s request_id=%s", method, request.request_id
            )
            raise JsonRpcProtocolError(
                METHOD_NOT_FOUND,
                f"Method not found: {method}",
                request_id=request.request_id,
            )
        except SpecValidationError as exc:
            logger.warning(
                "Spec validation failure method=%s request_id=%s error=%s",
                method,
                request.request_id,
                exc,
            )
            raise JsonRpcProtocolError(
                INVALID_PARAMS, str(exc), request_id=request.request_id
            ) from exc
        except SpecServiceError as exc:
            logger.warning(
                "Spec service failure method=%s request_id=%s code=%s error=%s",
                method,
                request.request_id,
                exc.code,
                exc,
            )
            raise JsonRpcProtocolError(
                SPEC_SERVICE_ERROR,
                str(exc),
                request_id=request.request_id,
                data={"code": exc.code},
            ) from exc
        except ValueError as exc:
            logger.warning(
                "Invalid params method=%s request_id=%s error=%s",
                method,
                request.request_id,
                exc,
            )
            raise JsonRpcProtocolError(
                INVALID_PARAMS, str(exc), request_id=request.request_id
            ) from exc
        finally:
            logger.info(
                "RPC ✓ method=%s request_id=%s duration_ms=%s",
                method,
                request.request_id,
                int((time.perf_counter() - started) * 1000),
            )

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        workspace = params.get("workspace")
        if workspace is not None and not isinstance(workspace, str):
            raise ValueError("initialize.workspace must be a string")
        # If the client did not supply a workspace, use the server's actual workspace.
        if workspace is None:
            workspace = str(self.tangles.workspace.resolve())
        capabilities = {
            "methods": [
                "initialize",
                "shutdown",
                "exit",
                "tangle/getTree",
                "tangle/getTreeDetailed",
                "tangle/getNode",
                "tangle/updateNode",
                "tangle/createSiblingNode",
                "tangle/indentNode",
                "tangle/outdentNode",
                "tangle/getNodeSourceRange",
                "tangle/getNodeCodeRefs",
                "tangle/setNodeCollapsed",
                "run/start",
                "run/stop",
                "run/status",
                "prime/message",
                "prime/newContext",
                "prime/cancel",
                "prime/history",
                "agent/launch",
                "agent/stop",
                "agent/close",
                "agent/list",
                "agent/steer",
                "agent/queue",
                "agent/subscribe",
                "agent/unsubscribe",
                "agent/answerQuestion",
                "ui/snapshot",
                "ui/openTab",
                "ui/closeTab",
                "ui/setActiveTab",
                "ui/updateLayout",
                "ui/setTheme",
                "ui/saveTab",
                "ui/nodeEdited",
                "fs/listDir",
                "fs/readFile",
                "fs/writeFile",
                "fs/search",
                "tangle/getBacklinks",
                "prompts/list",
                "prompts/get",
                "prompts/update",
                "prompts/reset",
                "refs/search",
                "refs/resolve",
                "refs/getDefinition",
                "refs/updateValue",
                "refs/backlinks",
                "refs/validate",
                "refs/reindex",
            ],
            "notifications": [
                "tangle/nodeCreated",
                "tangle/nodeChanged",
                "tangle/nodeDeleted",
                "tangle/treeChanged",
                "agent/stateChanged",
                "agent/toolBrief",
                "agent/toolCall",
                "agent/toolResult",
                "agent/message",
                "agent/questionAsked",
                "agent/lockChanged",
                "agent/event",
                "agent/token",
                "prime/token",
                "prime/toolCall",
                "prime/toolResult",
                "prime/done",
                "prime/subAgentLaunched",
                "prime/subAgentDone",
                "prime/agentLaunched",
                "approval/request",
                "clarificationRequired",
                "amendmentProposed",
                "run/output",
                "run/completed",
            ],
        }
        # Include current default model in response
        try:
            from taui.config.settings import load_settings

            default_model = load_settings().model.default
        except Exception:
            default_model = "unknown"

        # Resolve project title from spec root index.md (front-matter title → H1 → folder name)
        project_title: str | None = None
        try:
            index_path = self.tangles.spec_root / "index.md"
            if index_path.is_file():
                index_content = index_path.read_text(encoding="utf-8")
                # Try YAML front-matter title first
                if index_content.startswith("---\n"):
                    end = index_content.find("\n---\n", 4)
                    if end != -1:
                        try:
                            import yaml

                            fm = yaml.safe_load(index_content[4:end])
                            if isinstance(fm, dict) and isinstance(
                                fm.get("title"), str
                            ):
                                project_title = fm["title"].strip() or None
                        except Exception:
                            pass
                # Fall back to first H1 heading
                if not project_title:
                    import re

                    m = re.search(r"^#\s+(.+)$", index_content, re.MULTILINE)
                    if m:
                        project_title = m.group(1).strip() or None
        except Exception:
            pass
        # Last resort: workspace folder name
        if not project_title:
            project_title = self.tangles.workspace.resolve().name

        return {
            "protocolVersion": "1.0",
            "serverName": "taui-python-server",
            "workspace": workspace,
            "projectTitle": project_title,
            "capabilities": capabilities,
            "model": default_model,
        }

    async def _handle_spec_get_tree(self) -> dict[str, Any]:
        await self._ensure_tangles()
        nodes = []
        for node in await self.tangles.get_tree():
            node_data = node.to_dict()
            node_data["tangle_ref"] = node_data.get("spec_ref", "")
            nodes.append(node_data)
        return {"nodes": nodes}

    async def _handle_spec_get_tree_detailed(self) -> dict[str, Any]:
        await self._ensure_tangles()
        nodes = await self.tangles.get_tree()
        detailed_nodes = []
        for node in nodes:
            try:
                detailed_node = await self.tangles.get_node(node.spec_ref)
                node_dict = detailed_node.to_dict()
            except SpecServiceError:
                node_dict = node.to_dict()
            node_dict["tangle_ref"] = node_dict.get("spec_ref", "")
            detailed_nodes.append(node_dict)
        return {"nodes": detailed_nodes}

    async def _handle_spec_get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        tangle_ref = self._require_ref(params)
        await self._ensure_tangles()
        node = await self.tangles.get_node(tangle_ref)
        return {"node": _with_tangle_ref(node.to_dict())}

    async def _handle_spec_update_node(self, params: dict[str, Any]) -> DispatchResult:
        tangle_ref = self._require_ref(params)
        patch_raw = params.get("patch")
        if not isinstance(patch_raw, dict):
            raise ValueError("tangle/updateNode.patch must be an object")
        patch = SpecNodePatch.from_mapping(patch_raw)
        await self._ensure_tangles()
        update = await self.tangles.update_node(tangle_ref, patch)

        notifications: list[dict[str, Any]] = [
            notification_message(
                "tangle/nodeChanged", {"node": _with_tangle_ref(update.node.to_dict())}
            ),
        ]
        if update.tree_changed:
            notifications.append(
                notification_message(
                    "tangle/treeChanged",
                    {
                        "previous_tangle_ref": update.previous_spec_ref,
                        "tangle_ref": update.node.spec_ref,
                    },
                )
            )

        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_create_sibling_node(
        self, params: dict[str, Any]
    ) -> DispatchResult:
        tangle_ref = self._require_ref(params)
        await self._ensure_tangles()
        update = await self.tangles.create_sibling_node(tangle_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "tangle/treeChanged",
                {
                    "previous_tangle_ref": update.previous_spec_ref,
                    "tangle_ref": update.node.spec_ref,
                },
            ),
            notification_message(
                "tangle/nodeCreated", {"node": _with_tangle_ref(update.node.to_dict())}
            ),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_indent_node(self, params: dict[str, Any]) -> DispatchResult:
        tangle_ref = self._require_ref(params)
        await self._ensure_tangles()
        update = await self.tangles.indent_node(tangle_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "tangle/treeChanged",
                {
                    "previous_tangle_ref": update.previous_spec_ref,
                    "tangle_ref": update.node.spec_ref,
                },
            ),
            notification_message(
                "tangle/nodeChanged", {"node": _with_tangle_ref(update.node.to_dict())}
            ),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_outdent_node(self, params: dict[str, Any]) -> DispatchResult:
        tangle_ref = self._require_ref(params)
        await self._ensure_tangles()
        update = await self.tangles.outdent_node(tangle_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "tangle/treeChanged",
                {
                    "previous_tangle_ref": update.previous_spec_ref,
                    "tangle_ref": update.node.spec_ref,
                },
            ),
            notification_message(
                "tangle/nodeChanged", {"node": _with_tangle_ref(update.node.to_dict())}
            ),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_get_node_source_range(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        tangle_ref = self._require_ref(params)
        expanded = bool(params.get("expanded", False))
        max_lines = int(params.get("max_lines", 10))
        if max_lines < 1:
            max_lines = 10

        await self._ensure_tangles()
        node = await self.tangles.get_node(tangle_ref)
        file_path = self.tangles.workspace / node.file_path

        if not file_path.exists() or not file_path.is_file():
            return {
                "file_path": node.file_path,
                "line_start": node.line_start,
                "line_end": node.line_end,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": "file not found",
            }

        try:
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(self.tangles.workspace.resolve())):
                raise ValueError("path escapes workspace")
        except (OSError, ValueError) as exc:
            return {
                "file_path": node.file_path,
                "line_start": node.line_start,
                "line_end": node.line_end,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": str(exc),
            }

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "file_path": node.file_path,
                "line_start": node.line_start,
                "line_end": node.line_end,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": str(exc),
            }

        lines = content.splitlines()
        line_start = node.line_start
        line_end = node.line_end

        if line_start is None or line_end is None:
            line_start = 1
            line_end = min(max_lines, len(lines))

        preview_start = line_start
        if expanded:
            preview_end = line_end
            truncated = False
        else:
            preview_end = min(line_start + max_lines - 1, line_end)
            truncated = preview_end < line_end

        selected_lines = lines[preview_start - 1 : preview_end]
        selected_content = "\n".join(selected_lines)

        return {
            "file_path": node.file_path,
            "line_start": line_start,
            "line_end": line_end,
            "preview_start": preview_start,
            "preview_end": preview_end,
            "content": selected_content,
            "truncated": truncated,
        }

    async def _handle_spec_get_node_code_refs(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        tangle_ref = self._require_ref(params)
        max_lines = int(params.get("max_lines", 200))
        if max_lines < 1:
            max_lines = 200

        await self._ensure_tangles()
        node = await self.tangles.get_node(tangle_ref)
        refs: list[dict[str, Any]] = []
        spec_file = (self.tangles.workspace / node.file_path).resolve()
        for raw_ref in node.code_refs:
            refs.append(
                self._resolve_code_reference(
                    raw_ref=raw_ref,
                    spec_file=spec_file,
                    max_lines=max_lines,
                )
            )

        return {"refs": refs}

    async def _handle_spec_set_node_collapsed(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        tangle_ref = self._require_ref(params)
        collapsed = bool(params.get("collapsed", False))
        await self._ensure_tangles()
        node = await self.tangles.set_node_collapsed(tangle_ref, collapsed)
        return {"node": _with_tangle_ref(node.to_dict())}

    def _resolve_code_reference(
        self,
        *,
        raw_ref: str,
        spec_file: Path,
        max_lines: int,
    ) -> dict[str, Any]:
        # Keep markdown-escaped underscores usable in file paths.
        cleaned_ref = raw_ref.replace("\\_", "_").strip()
        path_part, _, line_part = cleaned_ref.partition("#")
        raw_path = path_part.strip()

        if not raw_path:
            return {
                "raw_ref": raw_ref,
                "file_path": "",
                "line_start": None,
                "line_end": None,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": "invalid code_ref path",
            }

        line_start: int | None = None
        line_end: int | None = None
        if line_part:
            match = CODE_REF_RANGE_RE.fullmatch(line_part.strip())
            if not match:
                return {
                    "raw_ref": raw_ref,
                    "file_path": raw_path,
                    "line_start": None,
                    "line_end": None,
                    "preview_start": None,
                    "preview_end": None,
                    "content": "",
                    "truncated": False,
                    "error": "invalid line range",
                }
            line_start = int(match.group("start"))
            line_end = int(match.group("end") or match.group("start"))
            if line_start <= 0:
                line_start = 1
            if line_end < line_start:
                line_end = line_start

        resolved, rel_path, resolve_error = self._resolve_workspace_file(
            raw_path=raw_path,
            spec_file=spec_file,
        )
        if resolved is None:
            return {
                "raw_ref": raw_ref,
                "file_path": rel_path,
                "line_start": line_start,
                "line_end": line_end,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": resolve_error or "path resolution failed",
            }

        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "raw_ref": raw_ref,
                "file_path": rel_path,
                "line_start": line_start,
                "line_end": line_end,
                "preview_start": None,
                "preview_end": None,
                "content": "",
                "truncated": False,
                "error": str(exc),
            }

        lines = content.splitlines()
        if not lines:
            return {
                "raw_ref": raw_ref,
                "file_path": rel_path,
                "line_start": 1 if line_start is None else line_start,
                "line_end": 1 if line_end is None else line_end,
                "preview_start": 1,
                "preview_end": 1,
                "content": "",
                "truncated": False,
            }

        if line_start is None or line_end is None:
            line_start = 1
            line_end = len(lines)

        line_start = min(max(1, line_start), len(lines))
        line_end = min(max(line_start, line_end), len(lines))
        preview_end = min(line_end, line_start + max_lines - 1)
        preview_start = line_start
        truncated = preview_end < line_end
        selected_content = "\n".join(lines[preview_start - 1 : preview_end])

        return {
            "raw_ref": raw_ref,
            "file_path": rel_path,
            "line_start": line_start,
            "line_end": line_end,
            "preview_start": preview_start,
            "preview_end": preview_end,
            "content": selected_content,
            "truncated": truncated,
        }

    def _resolve_workspace_file(
        self, *, raw_path: str, spec_file: Path
    ) -> tuple[Path | None, str, str | None]:
        workspace = self.tangles.workspace.resolve()
        # Project root is the spec_root itself (the directory passed via --path,
        # which is the parent of the specs/ subdirectory).  All relative code-ref
        # paths are resolved against it first so that `src/foo.py` always means
        # <project_root>/src/foo.py regardless of which spec file contains the ref.
        project_root = self.tangles.spec_root.resolve()
        path_obj = Path(raw_path)
        candidates: list[Path] = []
        if path_obj.is_absolute():
            candidates.append(path_obj)
        else:
            project_candidate = project_root / path_obj
            candidates.append(project_candidate)
            workspace_candidate = workspace / path_obj
            if workspace_candidate not in candidates:
                candidates.append(workspace_candidate)

        safe_candidate: Path | None = None
        safe_rel_path = raw_path

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue

            if not str(resolved).startswith(str(workspace)):
                continue

            try:
                relative = str(resolved.relative_to(project_root))
            except ValueError:
                try:
                    relative = str(resolved.relative_to(workspace))
                except ValueError:
                    relative = raw_path

            safe_candidate = resolved
            safe_rel_path = relative
            if resolved.exists() and resolved.is_file():
                return resolved, relative, None

        if safe_candidate is None:
            return None, raw_path, "path escapes workspace"

        return None, safe_rel_path, "file not found"

    async def _handle_run_start(self, params: dict[str, Any]) -> DispatchResult:
        tangle_ref = self._require_ref(params)
        command = self._require_str(params, "command")
        workdir = params.get("workdir", ".")

        if not isinstance(workdir, str):
            raise ValueError("workdir must be a string")

        workdir_path = Path(workdir)
        if not workdir_path.is_absolute():
            workdir_path = self.tangles.workspace / workdir_path

        try:
            workdir_path = workdir_path.resolve()
            if not str(workdir_path).startswith(str(self.tangles.workspace.resolve())):
                raise ValueError("workdir escapes workspace")
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid workdir: {exc}") from exc

        if not workdir_path.is_dir():
            raise ValueError(f"workdir does not exist: {workdir}")

        run_id = self.run_state.next_run_id
        self.run_state.next_run_id += 1

        run_process = RunProcess(
            run_id=run_id,
            tangle_ref=tangle_ref,
            command=command,
            workdir=str(workdir_path),
            started_at=time.time(),
        )
        self.run_state.current_process = run_process
        self.run_state.status = "running"
        self.run_state.run_id = run_id
        self.run_state.tangle_ref = tangle_ref

        asyncio.create_task(self._run_process(run_process))

        logger.info(
            "Run started run_id=%s tangle_ref=%s command=%s",
            run_id,
            tangle_ref,
            command,
        )

        return DispatchResult(result=run_process.to_dict(), notifications=[])

    async def _run_process(self, run: RunProcess) -> None:
        try:
            run.process = await asyncio.create_subprocess_shell(
                run.command,
                cwd=run.workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            assert run.process.stdout is not None
            assert run.process.stderr is not None

            async def read_stream(
                stream: asyncio.StreamReader, stream_name: str
            ) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    run.output_buffer.append(text)
                    notification = notification_message(
                        "run/output",
                        {"run_id": run.run_id, "stream": stream_name, "line": text},
                    )
                    self._emit_notification(notification)

            await asyncio.gather(
                read_stream(run.process.stdout, "stdout"),
                read_stream(run.process.stderr, "stderr"),
            )

            exit_code = await run.process.wait()
            run.exit_code = exit_code
            run.status = "completed"
            run.finished_at = time.time()

        except Exception as exc:
            run.status = "error"
            run.exit_code = -1
            run.finished_at = time.time()
            notification = notification_message(
                "run/output",
                {"run_id": run.run_id, "stream": "stderr", "line": str(exc)},
            )
            self._emit_notification(notification)
        finally:
            if self.run_state.current_process is run:
                self.run_state.status = "idle"

            notification = notification_message(
                "run/completed",
                {
                    "run_id": run.run_id,
                    "exit_code": run.exit_code,
                    "status": run.status,
                    "duration_ms": int(
                        (run.finished_at or time.time()) - run.started_at
                    )
                    * 1000,
                },
            )
            self._emit_notification(notification)

    async def _handle_run_stop(self) -> DispatchResult:
        run = self.run_state.current_process
        if run is None or run.process is None:
            self.run_state.status = "idle"
            return DispatchResult(result=self.run_state.to_dict(), notifications=[])

        try:
            run.process.terminate()
            try:
                await asyncio.wait_for(run.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                run.process.kill()
                await run.process.wait()

            run.status = "stopped"
            run.exit_code = run.process.returncode
            run.finished_at = time.time()
        except ProcessLookupError:
            pass

        self.run_state.status = "idle"

        notification = notification_message(
            "run/completed",
            {
                "run_id": run.run_id,
                "exit_code": run.exit_code,
                "status": run.status,
                "duration_ms": int((run.finished_at or time.time()) - run.started_at)
                * 1000,
            },
        )

        logger.info(
            "Run stopped run_id=%s exit_code=%s",
            run.run_id,
            run.exit_code,
        )

        return DispatchResult(
            result=self.run_state.to_dict(),
            notifications=[notification],
        )

    def _require_str(self, payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value

    def _require_ref(self, payload: dict[str, Any], *fields: str) -> str:
        candidates = list(fields) if fields else ["tangle_ref", "spec_ref"]
        for field in candidates:
            ref = payload.get(field)
            if isinstance(ref, str) and ref.strip():
                return ref
        joined = " or ".join(candidates)
        raise ValueError(f"{joined} must be a non-empty string")

    # ── Agent RPC handlers ─────────────────────────────────────────────────────

    # ── Prime ─────────────────────────────────────────────────────────────────

    def _get_prime(self) -> Any:
        """Lazily create and return the persistent PrimeAgent."""
        if self._prime_agent is None:
            from taui.agent.prime import PrimeAgent

            self._prime_agent = PrimeAgent(
                workspace=Path(self.tangles.workspace),
                spec_service=self.tangles,
                agent_manager=self.agent_manager,
                resolve_llm=lambda: self._resolve_llm_for_tier("medium", {}),
                emit_notification=self._emit_notification,
                history_db=self.history_db,
                stream_client=getattr(self, "stream_client", None),
            )
            self.agent_manager.set_prime_agent(self._prime_agent)
        return self._prime_agent

    async def _handle_prime_message(self, params: dict[str, Any]) -> DispatchResult:
        """Send a message to Prime.

        Prime is persistent — it maintains conversation history across calls.
        If Prime is idle, starts the think loop. If busy, interrupts and pivots.

        The RPC returns immediately with {ok: true}.  The think→tool→observe
        loop runs as a background task, emitting notifications:
          prime/token         — streamed text chunks
          prime/toolCall      — a tool call is starting
          prime/toolResult    — a tool call finished
          prime/interrupted   — Prime pivoted to a new message
          prime/stateChanged  — Prime state changed (thinking/tool_execution)
          prime/done          — the full response is complete

        Required params: messages (list of {role, content})
        """
        raw_messages = params.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise JsonRpcProtocolError(
                INVALID_PARAMS, "messages must be a non-empty list"
            )

        prime = self._get_prime()

        # Send the last user message (the new one) to persistent Prime
        last_msg = raw_messages[-1]
        if isinstance(last_msg, dict) and "content" in last_msg:
            await prime.send_message(
                last_msg["content"],
                role=last_msg.get("role", "user"),
            )

        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_prime_cancel(self) -> DispatchResult:
        """Cancel Prime's current think loop."""
        prime = self._get_prime()
        await prime.cancel()
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_prime_new_context(self, params: dict[str, Any]) -> DispatchResult:
        """Start a new Prime context, optionally seeded with a first user message."""
        prime = self._get_prime()
        seed = params.get("seed")
        if seed is not None and not isinstance(seed, str):
            raise JsonRpcProtocolError(
                INVALID_PARAMS, "seed must be a string when provided"
            )
        await prime.new_context(
            seed_message=(
                seed.strip() if isinstance(seed, str) and seed.strip() else None
            )
        )
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_prime_history(self, params: dict[str, Any]) -> DispatchResult:
        """Return Prime conversation history (supports pagination/full transcript)."""
        prime = self._get_prime()
        raw_before = params.get("before_seq")
        before_seq: int | None = None
        if raw_before is not None:
            if not isinstance(raw_before, int):
                raise JsonRpcProtocolError(
                    INVALID_PARAMS, "before_seq must be an integer when provided"
                )
            before_seq = raw_before

        raw_limit = params.get("limit")
        if raw_limit is None:
            limit = 50
        elif isinstance(raw_limit, int):
            limit = raw_limit
        else:
            raise JsonRpcProtocolError(
                INVALID_PARAMS, "limit must be an integer when provided"
            )

        full = bool(params.get("full", False))
        history_page = await prime.get_history_page(
            before_seq=before_seq,
            limit=limit,
            full=full,
        )
        return DispatchResult(
            result=history_page,
            notifications=[],
        )

    async def _handle_agent_launch(self, params: dict[str, Any]) -> DispatchResult:
        """Launch a root agent on a tangle branch.

        Required params: tangle_ref, task
        Optional params: tier (default "medium"), model, provider

        Returns: {agent_id, session_id}
        """
        tangle_ref = self._require_ref(params)
        task = self._require_str(params, "task")
        tier = str(params.get("tier", "medium"))
        if tier not in ("high", "medium", "low"):
            raise ValueError("tier must be 'high', 'medium', or 'low'")

        # Ensure DB is initialized
        await self._ensure_tangles()

        # Resolve LLM from tier — for now use a stub/None when no LLM is configured
        llm, model = self._resolve_llm_for_tier(tier, params)

        # Build a full ToolRegistry with all builtin + spec-tree tools
        from taui.tools.registry import ToolRegistry
        from taui.tools.builtins import register_builtin_tools
        from taui.tools.builtins.spec_tree import register_spec_tree_tools

        registry = ToolRegistry()
        register_builtin_tools(registry)
        register_spec_tree_tools(registry)

        runner = await self.agent_manager.launch(
            tangle_ref=tangle_ref,
            task=task,
            tier=tier,
            llm=llm,
            model=model,
            tool_registry=registry,
            spec_service=self.tangles,
            working_dir=self.tangles.workspace,
            agent_type=str(params.get("agent_type", "root")),
        )

        # Notify that a new agent started
        self._emit_notification(
            notification_message(
                "agent/stateChanged",
                {
                    "agent_id": runner.agent_id,
                    "state": "running",
                    "tangle_ref": tangle_ref,
                    "agent_type": runner.agent_type,
                    "display_name": runner.display_name,
                },
            )
        )

        return DispatchResult(
            result={
                "agent_id": runner.agent_id,
                "session_id": runner.session_id,
                "display_name": runner.display_name,
                "agent_type": runner.agent_type,
            },
            notifications=[],
        )

    def _resolve_llm_for_tier(
        self, tier: str, params: dict[str, Any]
    ) -> tuple[Any, str]:
        """Resolve LLM client + model string for the given tier.

        Falls back to a no-op stub if no provider is configured.
        """
        model = str(params.get("model", ""))
        provider = str(params.get("provider", ""))

        # Try to load configured LLM tier settings (ModelSettings may not have tier
        # attributes in all versions — use getattr to stay forward-compatible).
        try:
            from taui.config.settings import load_settings

            settings = load_settings()
            tier_cfg = getattr(settings.model, tier, None)
            if tier_cfg and not model:
                model = getattr(tier_cfg, "model", "") or model
            if tier_cfg and not provider:
                provider = getattr(tier_cfg, "provider", "") or provider
        except Exception:
            pass

        if not model:
            model = "claude-sonnet-4.6"

        # Try to instantiate a real LLM client
        if provider == "copilot" or not provider:
            try:
                from taui.auth.copilot import get_copilot_credentials
                from taui.llms.copilot import CopilotLLMClient

                creds = get_copilot_credentials()
                return CopilotLLMClient(creds), model
            except Exception as exc:
                logger.warning(
                    "Failed to initialize Copilot LLM (tier=%s): %s",
                    tier,
                    exc,
                )

        # Fall back to a no-op stub that immediately returns "done"
        logger.warning("No LLM provider available for tier=%s — using no-op stub", tier)
        return _NoOpLLMClient(), model

    async def _handle_agent_stop(self, params: dict[str, Any]) -> DispatchResult:
        agent_id = self._require_str(params, "agent_id")
        await self.agent_manager.stop(agent_id)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_close(self, params: dict[str, Any]) -> DispatchResult:
        """User-initiated close of a root agent tab.

        Cleans up event buffers, subscriptions, pending questions, and branch
        locks. If the agent is still running it is force-stopped first.
        Returns ``{"ok": True}`` on success; does not raise if the agent is
        already gone (idempotent).
        """
        agent_id = self._require_str(params, "agent_id")
        await self.agent_manager.close(agent_id)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_list(self) -> DispatchResult:
        await self._ensure_tangles()
        agents = self.agent_manager.list_active()
        return DispatchResult(result={"agents": agents}, notifications=[])

    async def _handle_agent_steer(self, params: dict[str, Any]) -> DispatchResult:
        """Inject a steer message into an active agent's queue.

        Required params: agent_id, message
        Returns: {ok: True}
        """
        agent_id = self._require_str(params, "agent_id")
        message = self._require_str(params, "message")
        await self.agent_manager.steer(agent_id, message)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_queue(self, params: dict[str, Any]) -> DispatchResult:
        """Enqueue a follow-up task for an agent to pick up after current task.

        Required params: agent_id, message
        Returns: {ok: True}
        """
        agent_id = self._require_str(params, "agent_id")
        message = self._require_str(params, "message")
        await self.agent_manager.queue(agent_id, message)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_subscribe(self, params: dict[str, Any]) -> DispatchResult:
        """Subscribe to detail events for an agent. Returns the event backlog.

        Required params: agent_id
        Optional params: from_offset (int) — if provided, uses durable streams
            for offset-based catch-up instead of the in-memory buffer.
        Returns: {backlog: [{agent_id, event_type, payload}, ...]}
        """
        agent_id = self._require_str(params, "agent_id")
        from_offset = params.get("from_offset")
        if from_offset is not None:
            # Use durable stream for offset-based catch-up (resumable)
            backlog = await self.agent_manager.subscribe_from_stream(
                agent_id, from_offset=int(from_offset)
            )
        else:
            # Legacy path: in-memory buffer
            backlog = self.agent_manager.subscribe(agent_id)
        return DispatchResult(result={"backlog": backlog}, notifications=[])

    async def _handle_agent_unsubscribe(self, params: dict[str, Any]) -> DispatchResult:
        """Unsubscribe from detail events for an agent.

        Required params: agent_id
        Returns: {ok: True}
        """
        agent_id = self._require_str(params, "agent_id")
        self.agent_manager.unsubscribe(agent_id)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_answer_question(
        self, params: dict[str, Any]
    ) -> DispatchResult:
        """Answer a pending agent question, unblocking the runner.

        Required params: question_node_ref, answer
        Returns: {ok: True, handled: bool}  — handled=True if a live runner processed it
        """
        question_node_ref = self._require_str(params, "question_node_ref")
        answer = self._require_str(params, "answer")
        handled = await self.agent_manager.answer_question(question_node_ref, answer)
        return DispatchResult(result={"ok": True, "handled": handled}, notifications=[])

    async def _handle_ui_snapshot(self) -> DispatchResult:
        settings = self.settings.load()
        await self.tangles.ensure_initialized()
        tree = [
            _with_tangle_ref(node.to_dict()) for node in await self.tangles.get_tree()
        ]
        sessions = await self.agent_manager.list_all()
        return DispatchResult(
            result={
                "tabs": settings.get("tabs", {}),
                "layout": settings.get("layout", {}),
                "theme": settings.get("theme", "dark"),
                "prompts": settings.get("prompts", {}),
                "tangleTree": tree,
                "agentSessions": sessions,
            },
            notifications=[],
        )

    async def _handle_ui_open_tab(self, params: dict[str, Any]) -> DispatchResult:
        path = self._require_str(params, "path")
        settings = self.settings.load()
        tabs = settings.setdefault("tabs", {})
        open_tabs = tabs.setdefault("open", [])
        if not isinstance(open_tabs, list):
            open_tabs = []
            tabs["open"] = open_tabs
        if path not in open_tabs:
            open_tabs.append(path)
        tabs["active"] = path
        self.settings.save(settings)
        return DispatchResult(result={"tabs": tabs}, notifications=[])

    async def _handle_ui_close_tab(self, params: dict[str, Any]) -> DispatchResult:
        path = self._require_str(params, "path")
        settings = self.settings.load()
        tabs = settings.setdefault("tabs", {})
        open_tabs = tabs.setdefault("open", [])
        if isinstance(open_tabs, list):
            tabs["open"] = [p for p in open_tabs if p != path]
        if tabs.get("active") == path:
            remaining = tabs.get("open", [])
            tabs["active"] = (
                remaining[0] if isinstance(remaining, list) and remaining else ""
            )
        self.settings.save(settings)
        return DispatchResult(result={"tabs": tabs}, notifications=[])

    async def _handle_ui_set_active_tab(self, params: dict[str, Any]) -> DispatchResult:
        path = self._require_str(params, "path")
        settings = self.settings.load()
        tabs = settings.setdefault("tabs", {})
        tabs["active"] = path
        self.settings.save(settings)
        return DispatchResult(result={"tabs": tabs}, notifications=[])

    async def _handle_ui_update_layout(self, params: dict[str, Any]) -> DispatchResult:
        layout = params.get("layout")
        if not isinstance(layout, dict):
            raise ValueError("layout must be an object")
        settings = self.settings.load()
        current = settings.setdefault("layout", {})
        if not isinstance(current, dict):
            current = {}
            settings["layout"] = current
        current.update(layout)
        self.settings.save(settings)
        return DispatchResult(result={"layout": current}, notifications=[])

    async def _handle_ui_set_theme(self, params: dict[str, Any]) -> DispatchResult:
        theme = self._require_str(params, "theme")
        settings = self.settings.load()
        settings["theme"] = theme
        self.settings.save(settings)
        return DispatchResult(result={"theme": theme}, notifications=[])

    async def _handle_ui_save_tab(self, params: dict[str, Any]) -> DispatchResult:
        path = self._require_str(params, "path")
        content = self._require_str(params, "content")
        workspace = self.tangles.workspace.resolve()
        target = (workspace / path).resolve()
        if not str(target).startswith(str(workspace)):
            raise ValueError("path escapes workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return DispatchResult(result={"ok": True, "path": path}, notifications=[])

    async def _handle_prompts_list(self) -> DispatchResult:
        return DispatchResult(
            result={"prompts": self.settings.list_prompts()}, notifications=[]
        )

    async def _handle_prompts_get(self, params: dict[str, Any]) -> DispatchResult:
        key = self._require_str(params, "key")
        prompt = self.settings.get_prompt(key)
        if prompt is None:
            raise ValueError(f"unknown prompt key: {key}")
        return DispatchResult(result={"key": key, "prompt": prompt}, notifications=[])

    async def _handle_prompts_update(self, params: dict[str, Any]) -> DispatchResult:
        key = self._require_str(params, "key")
        content = self._require_str(params, "content")
        prompt = self.settings.update_prompt(key, content)
        return DispatchResult(result={"key": key, "prompt": prompt}, notifications=[])

    async def _handle_prompts_reset(self, params: dict[str, Any]) -> DispatchResult:
        key = self._require_str(params, "key")
        prompt = self.settings.reset_prompt(key)
        if prompt is None:
            raise ValueError(f"unknown prompt key: {key}")
        return DispatchResult(result={"key": key, "prompt": prompt}, notifications=[])

    async def _handle_ui_node_edited(self, params: dict[str, Any]) -> DispatchResult:
        """Apply a user edit to a tangle node and steer any agent holding the lock.

        Required params: tangle_ref, new_markdown
        Optional params: old_markdown
        Returns: {ok: True}
        Notifications: tangle/nodeChanged (always), plus steer injected into locked agent
        """
        tangle_ref = self._require_ref(params)
        old_markdown = params.get("old_markdown", "")
        new_markdown = self._require_str(params, "new_markdown")

        # Apply edit to tangle tree
        patch = SpecNodePatch.from_mapping({"markdown": new_markdown})
        await self._ensure_tangles()
        update = await self.tangles.update_node(tangle_ref, patch)

        # Find if any active agent holds a lock on this branch
        lock = await self.agent_manager.db.get_branch_lock(tangle_ref)
        if lock is not None:
            locked_agent_id = lock["agent_id"]
            steer_msg = (
                f"<<USER_EDIT>> Node '{tangle_ref}' was edited by the user.\n"
                f"Previous content:\n{old_markdown}\n"
                f"New content:\n{new_markdown}\n"
                f"Adjust your work accordingly."
            )
            try:
                await self.agent_manager.steer(locked_agent_id, steer_msg)
            except ValueError:
                pass  # Agent no longer active — lock is stale

        notifications: list[dict[str, Any]] = [
            notification_message(
                "tangle/nodeChanged", {"node": _with_tangle_ref(update.node.to_dict())}
            ),
        ]
        if update.tree_changed:
            notifications.append(
                notification_message(
                    "tangle/treeChanged",
                    {
                        "previous_tangle_ref": update.previous_spec_ref,
                        "tangle_ref": update.node.spec_ref,
                    },
                )
            )
        return DispatchResult(result={"ok": True}, notifications=notifications)

    # ── Filesystem RPC handlers ────────────────────────────────────────────────

    async def _handle_fs_list_dir(self, params: dict[str, Any]) -> dict[str, Any]:
        """List files and folders in a directory.

        Required params: path (string, relative to workspace root)
        Returns: {entries: [{name, path, is_dir, extension}, ...]}
        """
        rel_path = params.get("path", "")
        if not isinstance(rel_path, str):
            raise ValueError("path must be a string")

        workspace = self.tangles.workspace.resolve()
        target = (workspace / rel_path).resolve() if rel_path else workspace

        # Security: ensure target is within workspace
        if not str(target).startswith(str(workspace)):
            raise ValueError("path escapes workspace")

        if not target.is_dir():
            raise ValueError(f"not a directory: {rel_path}")

        entries: list[dict[str, Any]] = []
        try:
            for item in sorted(
                target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            ):
                # Skip hidden files/dirs and __pycache__
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                try:
                    item_rel = str(item.relative_to(workspace))
                except ValueError:
                    continue
                entries.append(
                    {
                        "name": item.name,
                        "path": item_rel,
                        "is_dir": item.is_dir(),
                        "extension": item.suffix.lstrip(".") if item.suffix else "",
                    }
                )
        except PermissionError:
            pass

        return {"entries": entries}

    async def _handle_fs_read_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read file content with optional parsed frontmatter.

        Required params: path (string, relative to workspace root)
        Returns: {content: string, frontmatter?: object}
        """
        rel_path = self._require_str(params, "path")
        workspace = self.tangles.workspace.resolve()
        target = (workspace / rel_path).resolve()

        # Security: ensure target is within workspace
        if not str(target).startswith(str(workspace)):
            raise ValueError("path escapes workspace")

        if not target.is_file():
            raise ValueError(f"not a file: {rel_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read file: {exc}") from exc

        # Parse YAML frontmatter if present
        frontmatter: dict[str, Any] | None = None
        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end != -1:
                fm_text = content[4:end]
                try:
                    import yaml

                    frontmatter = yaml.safe_load(fm_text)
                    if not isinstance(frontmatter, dict):
                        frontmatter = None
                except Exception:
                    frontmatter = None

        result: dict[str, Any] = {"content": content}
        if frontmatter is not None:
            result["frontmatter"] = frontmatter
        return result

    async def _handle_fs_write_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write content to a file.

        Required params: path (string), content (string)
        Returns: {ok: True}
        """
        rel_path = self._require_str(params, "path")
        content = params.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content must be a string")

        workspace = self.tangles.workspace.resolve()
        target = (workspace / rel_path).resolve()

        # Security: ensure target is within workspace
        if not str(target).startswith(str(workspace)):
            raise ValueError("path escapes workspace")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot write file: {exc}") from exc

        return {"ok": True}

    async def _handle_fs_create_dir(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a directory.

        Required params: path (string)
        Returns: {ok: True}
        """
        rel_path = self._require_str(params, "path")

        workspace = self.tangles.workspace.resolve()
        target = (workspace / rel_path).resolve()

        # Security: ensure target is within workspace
        if not str(target).startswith(str(workspace)):
            raise ValueError("path escapes workspace")

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"cannot create directory: {exc}") from exc

        return {"ok": True}

    async def _handle_fs_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Full-text search across tangle files.

        Required params: query (string)
        Optional params: regex (bool), case_sensitive (bool), file_pattern (string)
        Returns: {results: [{file_path, line_number, line_content, match_start, match_end}, ...]}
        """
        query = self._require_str(params, "query")
        use_regex = bool(params.get("regex", False))
        case_sensitive = bool(params.get("case_sensitive", False))
        file_pattern = params.get("file_pattern", "*.md")
        if not isinstance(file_pattern, str):
            file_pattern = "*.md"

        workspace = self.tangles.workspace.resolve()
        results: list[dict[str, Any]] = []
        max_results = 200

        # Compile pattern
        if use_regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(query, flags)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc
        else:
            if not case_sensitive:
                query_lower = query.lower()
            pattern = None

        # Walk workspace files
        import fnmatch

        for file_path in sorted(workspace.rglob("*")):
            if len(results) >= max_results:
                break
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            if not fnmatch.fnmatch(file_path.name, file_pattern):
                continue

            # Skip binary files, node_modules, .git, etc.
            rel = str(file_path.relative_to(workspace))
            skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "target"}
            if any(part in skip_dirs for part in rel.split("/")):
                continue

            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(text.splitlines(), start=1):
                if len(results) >= max_results:
                    break

                if pattern:
                    m = pattern.search(line)
                    if m:
                        results.append(
                            {
                                "file_path": rel,
                                "line_number": line_num,
                                "line_content": line[:500],
                                "match_start": m.start(),
                                "match_end": m.end(),
                            }
                        )
                else:
                    search_line = line if case_sensitive else line.lower()
                    search_query = query if case_sensitive else query_lower
                    idx = search_line.find(search_query)
                    if idx != -1:
                        results.append(
                            {
                                "file_path": rel,
                                "line_number": line_num,
                                "line_content": line[:500],
                                "match_start": idx,
                                "match_end": idx + len(query),
                            }
                        )

        return {"results": results}

    async def _handle_spec_get_backlinks(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Find files that link to the given file.

        Required params: file_path (string, relative to workspace)
        Returns: {backlinks: [{file_path, line_number, context}, ...]}
        """
        target_path = self._require_str(params, "file_path")
        workspace = self.tangles.workspace.resolve()
        backlinks: list[dict[str, Any]] = []

        # Extract the file name and possible references to it
        target_name = Path(target_path).stem
        search_patterns = [target_path, target_name]

        for file_path in sorted(workspace.rglob("*.md")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(workspace))
            if rel == target_path:
                continue  # Don't include self

            skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "target"}
            if any(part in skip_dirs for part in rel.split("/")):
                continue

            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(text.splitlines(), start=1):
                for pattern in search_patterns:
                    if pattern in line:
                        backlinks.append(
                            {
                                "file_path": rel,
                                "line_number": line_num,
                                "context": line.strip()[:200],
                            }
                        )
                        break  # Only count first match per line

        return {"backlinks": backlinks}

    # ── Semantic refs RPC handlers ─────────────────────────────────────────────

    async def _ensure_symbol_infra(self) -> None:
        """Lazily initialise the symbol indexer, DB, and resolver."""
        if self._symbol_db is not None:
            return
        from taui.symbols.db import SymbolDB
        from taui.symbols.indexer import SymbolIndexer
        from taui.symbols.resolver import SymbolResolver

        await self._ensure_tangles()
        conn = self.tangles.db._conn
        self._symbol_db = SymbolDB(conn)
        self._symbol_indexer = SymbolIndexer(self.tangles.workspace)
        self._symbol_resolver = SymbolResolver(self.tangles.workspace, self._symbol_db)

    async def _handle_refs_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search the symbol index.

        params: { query: string, kind?: string, scope?: string, limit?: int }
        returns: { symbols: SymbolEntry[] }
        """
        await self._ensure_symbol_infra()
        query = self._require_str(params, "query")
        kind = params.get("kind")
        scope = params.get("scope")
        limit = int(params.get("limit", 50))
        if limit < 1:
            limit = 50

        symbols = await self._symbol_db.search_symbols(
            query, kind=kind, scope=scope, limit=limit
        )
        return {"symbols": [s.to_dict() for s in symbols]}

    async def _handle_refs_resolve(self, params: dict[str, Any]) -> dict[str, Any]:
        """Resolve a semantic reference.

        params: { ref: SemanticRef }
        returns: ResolvedRef
        """
        await self._ensure_symbol_infra()
        ref_raw = params.get("ref")
        if not isinstance(ref_raw, dict):
            raise ValueError("refs/resolve.ref must be an object")

        from taui.symbols.models import SemanticRef

        ref = SemanticRef.from_dict(ref_raw)
        resolved = await self._symbol_resolver.resolve(ref)
        return resolved.to_dict()

    async def _handle_refs_get_definition(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Get a symbol definition with source context.

        params: { file_path: string, symbol_name: string }
        returns: { symbol, source_text, context_before, context_after }
        """
        await self._ensure_symbol_infra()
        file_path = self._require_str(params, "file_path")
        symbol_name = self._require_str(params, "symbol_name")

        symbol = await self._symbol_db.get_symbol(file_path, symbol_name)
        if symbol is None:
            return {
                "symbol": None,
                "error": f"Symbol '{symbol_name}' not found in {file_path}",
            }

        abs_path = self.tangles.workspace / file_path
        source_text = ""
        context_before = ""
        context_after = ""
        if abs_path.exists():
            try:
                lines = abs_path.read_text(encoding="utf-8").splitlines()
                start = max(0, symbol.line_start - 1)
                end = min(len(lines), symbol.line_end)
                source_text = "\n".join(lines[start:end])
                ctx_start = max(0, start - 3)
                context_before = "\n".join(lines[ctx_start:start])
                ctx_end = min(len(lines), end + 3)
                context_after = "\n".join(lines[end:ctx_end])
            except OSError:
                pass

        return {
            "symbol": symbol.to_dict(),
            "source_text": source_text,
            "context_before": context_before,
            "context_after": context_after,
        }

    async def _handle_refs_update_value(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update a writable variable ref value in source.

        params: { file_path: string, symbol_name: string, new_value: string }
        returns: { success, old_value, new_value, line }
        """
        await self._ensure_symbol_infra()
        file_path = self._require_str(params, "file_path")
        symbol_name = self._require_str(params, "symbol_name")
        new_value = self._require_str(params, "new_value")

        result = await self._symbol_resolver.update_value(
            file_path, symbol_name, new_value
        )

        # Re-index the file after edit
        if result.get("success"):
            abs_path = self.tangles.workspace / file_path
            if abs_path.exists():
                new_symbols = self._symbol_indexer.index_file(abs_path)
                await self._symbol_db.delete_symbols_for_file(file_path)
                if new_symbols:
                    await self._symbol_db.upsert_symbols(new_symbols)

        return result

    async def _handle_refs_backlinks(self, params: dict[str, Any]) -> dict[str, Any]:
        """Find spec nodes referencing a file or symbol.

        params: { file_path: string, symbol_name?: string }
        returns: { refs: RefIndexEntry[], count: int }
        """
        await self._ensure_symbol_infra()
        file_path = self._require_str(params, "file_path")
        symbol_name = params.get("symbol_name")

        refs = await self._symbol_db.get_backlinks_for_file(
            file_path, symbol_name=symbol_name
        )
        return {"refs": refs, "count": len(refs)}

    async def _handle_refs_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate all semantic refs or refs on a specific tangle node.

        params: { tangle_ref?: string }
        returns: { results: [{ ref, diagnostic, detail }] }
        """
        await self._ensure_symbol_infra()
        from taui.symbols.models import SemanticRef

        tangle_ref = params.get("tangle_ref") or params.get("spec_ref")
        if isinstance(tangle_ref, str) and tangle_ref.strip():
            await self._ensure_tangles()
            node = await self.tangles.get_node(tangle_ref)
            ref_entries = await self._symbol_db.get_refs_for_node(node.id)
        else:
            ref_entries = await self._symbol_db.validate_all_refs()

        results = []
        for entry in ref_entries:
            ref = SemanticRef(
                file_path=entry["file_path"],
                symbol_path=entry.get("symbol_path"),
                ref_kind=entry["ref_kind"],
            )
            resolved = await self._symbol_resolver.resolve(ref)
            # Update diagnostic in DB
            await self._symbol_db.update_ref_diagnostic(
                entry["id"], resolved.diagnostic
            )
            results.append(
                {
                    "ref": ref.to_dict(),
                    "diagnostic": resolved.diagnostic,
                    "detail": resolved.fallback_reason or "ok",
                }
            )

        return {"results": results}

    async def _handle_refs_reindex(self, params: dict[str, Any]) -> dict[str, Any]:
        """Trigger a full or incremental re-index of the project symbols.

        params: { file_path?: string }  (if omitted, full re-index)
        returns: { indexed_files: int, symbols: int }
        """
        await self._ensure_symbol_infra()
        file_path = params.get("file_path")

        if file_path and isinstance(file_path, str):
            abs_path = self.tangles.workspace / file_path
            if not abs_path.exists():
                return {"indexed_files": 0, "symbols": 0, "error": "File not found"}
            await self._symbol_db.delete_symbols_for_file(file_path)
            symbols = self._symbol_indexer.index_file(abs_path)
            if symbols:
                await self._symbol_db.upsert_symbols(symbols)
            return {"indexed_files": 1, "symbols": len(symbols)}

        # Full re-index
        symbols = self._symbol_indexer.scan_project()
        # Clear and re-insert all
        await self._symbol_db._conn.execute("DELETE FROM symbols")
        await self._symbol_db._conn.commit()
        if symbols:
            await self._symbol_db.upsert_symbols(symbols)
        # Count unique files
        files = {s.file_path for s in symbols}
        return {"indexed_files": len(files), "symbols": len(symbols)}
