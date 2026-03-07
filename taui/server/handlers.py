from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from .state import RunState


@dataclass(slots=True)
class DispatchResult:
    result: dict[str, Any] | None
    notifications: list[dict[str, Any]]


class MethodHandlers:
    def __init__(self, workspace: Path | str | None = None) -> None:
        self.specs = SpecService(workspace=workspace)
        self.run_state = RunState()

    async def dispatch(self, request: JsonRpcRequest) -> DispatchResult:
        method = request.method
        params = request.params

        try:
            if method == "initialize":
                return DispatchResult(result=self._handle_initialize(params), notifications=[])
            if method == "shutdown":
                return DispatchResult(result={"ok": True}, notifications=[])
            if method == "exit":
                return DispatchResult(result=None, notifications=[])
            if method == "spec/getTree":
                return DispatchResult(result=self._handle_spec_get_tree(), notifications=[])
            if method == "spec/getNode":
                return DispatchResult(
                    result=self._handle_spec_get_node(params), notifications=[]
                )
            if method == "spec/updateNode":
                return self._handle_spec_update_node(params)
            if method == "run/start":
                return DispatchResult(result=self._handle_run_start(params), notifications=[])
            if method == "run/stop":
                return DispatchResult(result=self._handle_run_stop(), notifications=[])
            if method == "run/status":
                return DispatchResult(result=self.run_state.to_dict(), notifications=[])
        except SpecValidationError as exc:
            raise JsonRpcProtocolError(
                INVALID_PARAMS, str(exc), request_id=request.request_id
            ) from exc
        except SpecServiceError as exc:
            raise JsonRpcProtocolError(
                SPEC_SERVICE_ERROR,
                str(exc),
                request_id=request.request_id,
                data={"code": exc.code},
            ) from exc
        except ValueError as exc:
            raise JsonRpcProtocolError(
                INVALID_PARAMS, str(exc), request_id=request.request_id
            ) from exc

        raise JsonRpcProtocolError(
            METHOD_NOT_FOUND, f"Method not found: {method}", request_id=request.request_id
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
            ],
        }
        return {
            "protocolVersion": "1.0",
            "serverName": "taui-python-server",
            "workspace": workspace,
            "capabilities": capabilities,
        }

    def _handle_spec_get_tree(self) -> dict[str, Any]:
        nodes = [node.to_dict() for node in self.specs.get_tree()]
        return {"nodes": nodes}

    def _handle_spec_get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        spec_ref = self._require_str(params, "spec_ref")
        node = self.specs.get_node(spec_ref)
        return {"node": node.to_dict()}

    def _handle_spec_update_node(self, params: dict[str, Any]) -> DispatchResult:
        spec_ref = self._require_str(params, "spec_ref")
        patch_raw = params.get("patch")
        if not isinstance(patch_raw, dict):
            raise ValueError("spec/updateNode.patch must be an object")
        patch = SpecNodePatch.from_mapping(patch_raw)
        update = self.specs.update_node(spec_ref, patch)

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

    def _handle_run_start(self, params: dict[str, Any]) -> dict[str, Any]:
        spec_ref = self._require_str(params, "spec_ref")
        run_id = self.run_state.next_run_id
        self.run_state.next_run_id += 1
        self.run_state.status = "running"
        self.run_state.run_id = run_id
        self.run_state.spec_ref = spec_ref
        return self.run_state.to_dict()

    def _handle_run_stop(self) -> dict[str, Any]:
        if self.run_state.status == "running":
            self.run_state.status = "stopped"
        else:
            self.run_state.status = "idle"
        return self.run_state.to_dict()

    def _require_str(self, payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value
