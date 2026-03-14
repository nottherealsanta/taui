from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import time
from typing import Any, Callable

from taui.specs import (
    SpecNodePatch,
    SpecService,
    SpecServiceError,
    SpecValidationError,
)
from taui.agent.manager import AgentManager

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
        specs_path: Path | str | None = None,
        dev_mode: bool = False,
    ) -> None:
        self.specs = SpecService(
            workspace=workspace, specs_path=specs_path, dev_mode=dev_mode
        )
        self.run_state = RunState()
        self._notification_callback: NotificationCallback | None = None
        self.agent_manager = AgentManager(db=self.specs.db)

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
            if method == "spec/getTree":
                return DispatchResult(
                    result=await self._handle_spec_get_tree(), notifications=[]
                )
            if method == "spec/getTreeDetailed":
                return DispatchResult(
                    result=await self._handle_spec_get_tree_detailed(), notifications=[]
                )
            if method == "spec/getNode":
                return DispatchResult(
                    result=await self._handle_spec_get_node(params), notifications=[]
                )
            if method == "spec/updateNode":
                return await self._handle_spec_update_node(params)
            if method == "spec/createSiblingNode":
                return await self._handle_spec_create_sibling_node(params)
            if method == "spec/indentNode":
                return await self._handle_spec_indent_node(params)
            if method == "spec/outdentNode":
                return await self._handle_spec_outdent_node(params)
            if method == "spec/getNodeSourceRange":
                return DispatchResult(
                    result=await self._handle_spec_get_node_source_range(params),
                    notifications=[],
                )
            if method == "spec/getNodeCodeRefs":
                return DispatchResult(
                    result=await self._handle_spec_get_node_code_refs(params),
                    notifications=[],
                )
            if method == "spec/setNodeCollapsed":
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
            if method == "agent/launch":
                return await self._handle_agent_launch(params)
            if method == "agent/stop":
                return await self._handle_agent_stop(params)
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
            if method == "ui/nodeEdited":
                return await self._handle_ui_node_edited(params)
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
        capabilities = {
            "methods": [
                "initialize",
                "shutdown",
                "exit",
                "spec/getTree",
                "spec/getTreeDetailed",
                "spec/getNode",
                "spec/updateNode",
                "spec/createSiblingNode",
                "spec/indentNode",
                "spec/outdentNode",
                "spec/getNodeSourceRange",
                "spec/getNodeCodeRefs",
                "spec/setNodeCollapsed",
                "run/start",
                "run/stop",
                "run/status",
                "agent/launch",
                "agent/stop",
                "agent/list",
                "agent/steer",
                "agent/queue",
                "agent/subscribe",
                "agent/unsubscribe",
                "agent/answerQuestion",
                "ui/nodeEdited",
            ],
            "notifications": [
                "spec/nodeCreated",
                "spec/nodeChanged",
                "spec/nodeDeleted",
                "spec/treeChanged",
                "agent/stateChanged",
                "agent/toolBrief",
                "agent/toolCall",
                "agent/toolResult",
                "agent/message",
                "agent/questionAsked",
                "agent/lockChanged",
                "agent/event",
                "agent/token",
                "approval/request",
                "clarificationRequired",
                "amendmentProposed",
                "run/output",
                "run/completed",
            ],
        }
        return {
            "protocolVersion": "1.0",
            "serverName": "taui-python-server",
            "workspace": workspace,
            "capabilities": capabilities,
        }

    async def _handle_spec_get_tree(self) -> dict[str, Any]:
        nodes = [node.to_dict() for node in await self.specs.get_tree()]
        return {"nodes": nodes}

    async def _handle_spec_get_tree_detailed(self) -> dict[str, Any]:
        nodes = await self.specs.get_tree()
        detailed_nodes = []
        for node in nodes:
            try:
                detailed_node = await self.specs.get_node(node.spec_ref)
                node_dict = detailed_node.to_dict()
            except SpecServiceError:
                node_dict = node.to_dict()
            detailed_nodes.append(node_dict)
        return {"nodes": detailed_nodes}

    async def _handle_spec_get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        spec_ref = self._require_str(params, "spec_ref")
        node = await self.specs.get_node(spec_ref)
        return {"node": node.to_dict()}

    async def _handle_spec_update_node(self, params: dict[str, Any]) -> DispatchResult:
        spec_ref = self._require_str(params, "spec_ref")
        patch_raw = params.get("patch")
        if not isinstance(patch_raw, dict):
            raise ValueError("spec/updateNode.patch must be an object")
        patch = SpecNodePatch.from_mapping(patch_raw)
        update = await self.specs.update_node(spec_ref, patch)

        notifications: list[dict[str, Any]] = [
            notification_message("spec/nodeChanged", {"node": update.node.to_dict()})
        ]
        if update.tree_changed:
            notifications.append(
                notification_message(
                    "spec/treeChanged",
                    {
                        "previous_spec_ref": update.previous_spec_ref,
                        "spec_ref": update.node.spec_ref,
                    },
                )
            )

        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_create_sibling_node(
        self, params: dict[str, Any]
    ) -> DispatchResult:
        spec_ref = self._require_str(params, "spec_ref")
        update = await self.specs.create_sibling_node(spec_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "spec/treeChanged",
                {
                    "previous_spec_ref": update.previous_spec_ref,
                    "spec_ref": update.node.spec_ref,
                },
            ),
            notification_message("spec/nodeCreated", {"node": update.node.to_dict()}),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_indent_node(self, params: dict[str, Any]) -> DispatchResult:
        spec_ref = self._require_str(params, "spec_ref")
        update = await self.specs.indent_node(spec_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "spec/treeChanged",
                {
                    "previous_spec_ref": update.previous_spec_ref,
                    "spec_ref": update.node.spec_ref,
                },
            ),
            notification_message("spec/nodeChanged", {"node": update.node.to_dict()}),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_outdent_node(self, params: dict[str, Any]) -> DispatchResult:
        spec_ref = self._require_str(params, "spec_ref")
        update = await self.specs.outdent_node(spec_ref)
        notifications: list[dict[str, Any]] = [
            notification_message(
                "spec/treeChanged",
                {
                    "previous_spec_ref": update.previous_spec_ref,
                    "spec_ref": update.node.spec_ref,
                },
            ),
            notification_message("spec/nodeChanged", {"node": update.node.to_dict()}),
        ]
        return DispatchResult(result=update.to_dict(), notifications=notifications)

    async def _handle_spec_get_node_source_range(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        spec_ref = self._require_str(params, "spec_ref")
        expanded = bool(params.get("expanded", False))
        max_lines = int(params.get("max_lines", 10))
        if max_lines < 1:
            max_lines = 10

        node = await self.specs.get_node(spec_ref)
        file_path = self.specs.workspace / node.file_path

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
            if not str(file_path).startswith(str(self.specs.workspace.resolve())):
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
        spec_ref = self._require_str(params, "spec_ref")
        max_lines = int(params.get("max_lines", 200))
        if max_lines < 1:
            max_lines = 200

        node = await self.specs.get_node(spec_ref)
        refs: list[dict[str, Any]] = []
        spec_file = (self.specs.workspace / node.file_path).resolve()
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
        spec_ref = self._require_str(params, "spec_ref")
        collapsed = bool(params.get("collapsed", False))
        node = await self.specs.set_node_collapsed(spec_ref, collapsed)
        return {"node": node.to_dict()}

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
        workspace = self.specs.workspace.resolve()
        # Project root is the spec_root itself (the directory passed via --path,
        # which is the parent of the specs/ subdirectory).  All relative code-ref
        # paths are resolved against it first so that `src/foo.py` always means
        # <project_root>/src/foo.py regardless of which spec file contains the ref.
        project_root = self.specs.spec_root.resolve()
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
        spec_ref = self._require_str(params, "spec_ref")
        command = self._require_str(params, "command")
        workdir = params.get("workdir", ".")

        if not isinstance(workdir, str):
            raise ValueError("workdir must be a string")

        workdir_path = Path(workdir)
        if not workdir_path.is_absolute():
            workdir_path = self.specs.workspace / workdir_path

        try:
            workdir_path = workdir_path.resolve()
            if not str(workdir_path).startswith(str(self.specs.workspace.resolve())):
                raise ValueError("workdir escapes workspace")
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid workdir: {exc}") from exc

        if not workdir_path.is_dir():
            raise ValueError(f"workdir does not exist: {workdir}")

        run_id = self.run_state.next_run_id
        self.run_state.next_run_id += 1

        run_process = RunProcess(
            run_id=run_id,
            spec_ref=spec_ref,
            command=command,
            workdir=str(workdir_path),
            started_at=time.time(),
        )
        self.run_state.current_process = run_process
        self.run_state.status = "running"
        self.run_state.run_id = run_id
        self.run_state.spec_ref = spec_ref

        asyncio.create_task(self._run_process(run_process))

        logger.info(
            "Run started run_id=%s spec_ref=%s command=%s",
            run_id,
            spec_ref,
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

    # ── Agent RPC handlers ─────────────────────────────────────────────────────

    async def _handle_agent_launch(self, params: dict[str, Any]) -> DispatchResult:
        """Launch a root agent on a spec branch.

        Required params: spec_ref, task
        Optional params: tier (default "mid"), model, provider

        Returns: {agent_id, session_id}
        """
        spec_ref = self._require_str(params, "spec_ref")
        task = self._require_str(params, "task")
        tier = str(params.get("tier", "mid"))
        if tier not in ("senior", "mid", "junior"):
            raise ValueError("tier must be 'senior', 'mid', or 'junior'")

        # Ensure DB is initialized
        await self.specs.ensure_initialized()

        # Resolve LLM from tier — for now use a stub/None when no LLM is configured
        llm, model = self._resolve_llm_for_tier(tier, params)

        # Build a minimal ToolRegistry with spec-tree tools
        from taui.tools.registry import ToolRegistry
        from taui.tools.builtins.spec_tree import register_spec_tree_tools

        registry = ToolRegistry()
        register_spec_tree_tools(registry)

        runner = await self.agent_manager.launch(
            spec_ref=spec_ref,
            task=task,
            tier=tier,
            llm=llm,
            model=model,
            tool_registry=registry,
            spec_service=self.specs,
        )

        # Notify that a new agent started
        self._emit_notification(
            notification_message(
                "agent/stateChanged",
                {
                    "agent_id": runner.agent_id,
                    "state": "running",
                    "spec_ref": spec_ref,
                },
            )
        )

        return DispatchResult(
            result={"agent_id": runner.agent_id, "session_id": runner.session_id},
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
            model = "claude-haiku-4.5"

        # Try to instantiate a real LLM client
        if provider == "copilot" or not provider:
            try:
                from taui.auth.copilot import get_copilot_credentials
                from taui.llms.copilot import CopilotLLMClient

                creds = get_copilot_credentials()
                return CopilotLLMClient(creds), model
            except Exception:
                pass

        # Fall back to a no-op stub that immediately returns "done"
        return _NoOpLLMClient(), model

    async def _handle_agent_stop(self, params: dict[str, Any]) -> DispatchResult:
        agent_id = self._require_str(params, "agent_id")
        await self.agent_manager.stop(agent_id)
        return DispatchResult(result={"ok": True}, notifications=[])

    async def _handle_agent_list(self) -> DispatchResult:
        await self.specs.ensure_initialized()
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
        Returns: {backlog: [{agent_id, event_type, payload}, ...]}
        """
        agent_id = self._require_str(params, "agent_id")
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

    async def _handle_ui_node_edited(self, params: dict[str, Any]) -> DispatchResult:
        """Apply a user edit to a spec node and steer any agent holding the lock.

        Required params: spec_ref, new_markdown
        Optional params: old_markdown
        Returns: {ok: True}
        Notifications: spec/nodeChanged (always), plus steer injected into locked agent
        """
        spec_ref = self._require_str(params, "spec_ref")
        old_markdown = params.get("old_markdown", "")
        new_markdown = self._require_str(params, "new_markdown")

        # Apply edit to spec tree
        patch = SpecNodePatch.from_mapping({"markdown": new_markdown})
        update = await self.specs.update_node(spec_ref, patch)

        # Find if any active agent holds a lock on this branch
        lock = await self.agent_manager.db.get_branch_lock(spec_ref)
        if lock is not None:
            locked_agent_id = lock["agent_id"]
            steer_msg = (
                f"<<USER_EDIT>> Node '{spec_ref}' was edited by the user.\n"
                f"Previous content:\n{old_markdown}\n"
                f"New content:\n{new_markdown}\n"
                f"Adjust your work accordingly."
            )
            try:
                await self.agent_manager.steer(locked_agent_id, steer_msg)
            except ValueError:
                pass  # Agent no longer active — lock is stale

        notifications: list[dict[str, Any]] = [
            notification_message("spec/nodeChanged", {"node": update.node.to_dict()})
        ]
        if update.tree_changed:
            notifications.append(
                notification_message(
                    "spec/treeChanged",
                    {
                        "previous_spec_ref": update.previous_spec_ref,
                        "spec_ref": update.node.spec_ref,
                    },
                )
            )
        return DispatchResult(result={"ok": True}, notifications=notifications)
