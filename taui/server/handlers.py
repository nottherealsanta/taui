from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any, Callable

from taui.specs import (
    SpecNodePatch,
    SpecService,
    SpecServiceError,
    SpecValidationError,
)

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


NotificationCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class DispatchResult:
    result: dict[str, Any] | None
    notifications: list[dict[str, Any]]


class MethodHandlers:
    def __init__(
        self,
        workspace: Path | str | None = None,
        specs_path: Path | str | None = None,
    ) -> None:
        self.specs = SpecService(workspace=workspace, specs_path=specs_path)
        self.run_state = RunState()
        self._notification_callback: NotificationCallback | None = None
        self._notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        self._notification_callback = callback

    async def drain_notifications(self) -> None:
        while True:
            try:
                notification = self._notification_queue.get_nowait()
                if self._notification_callback:
                    self._notification_callback(notification)
            except asyncio.QueueEmpty:
                break

    async def dispatch(self, request: JsonRpcRequest) -> DispatchResult:
        method = request.method
        params = request.params
        started = time.perf_counter()
        logger.debug(
            "Dispatching method=%s request_id=%s notification=%s",
            method,
            request.request_id,
            request.is_notification,
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
            if method == "spec/getNode":
                return DispatchResult(
                    result=await self._handle_spec_get_node(params), notifications=[]
                )
            if method == "spec/updateNode":
                return await self._handle_spec_update_node(params)
            if method == "spec/getNodeSourceRange":
                return DispatchResult(
                    result=await self._handle_spec_get_node_source_range(params),
                    notifications=[],
                )
            if method == "run/start":
                return await self._handle_run_start(params)
            if method == "run/stop":
                return await self._handle_run_stop()
            if method == "run/status":
                return DispatchResult(result=self.run_state.to_dict(), notifications=[])
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
            logger.debug(
                "Dispatch complete method=%s request_id=%s duration_ms=%s",
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
                "spec/getNode",
                "spec/updateNode",
                "spec/getNodeSourceRange",
                "run/start",
                "run/stop",
                "run/status",
            ],
            "notifications": [
                "spec/nodeChanged",
                "spec/treeChanged",
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
                    await self._notification_queue.put(notification)

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
            await self._notification_queue.put(notification)
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
            await self._notification_queue.put(notification)

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
