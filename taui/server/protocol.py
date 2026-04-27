"""JSON-RPC 2.0 protocol helpers for the web server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

RequestID = int | str


@dataclass(slots=True)
class JsonRpcRequest:
    method: str
    params: dict[str, Any]
    request_id: RequestID | None

    @property
    def is_notification(self) -> bool:
        return self.request_id is None


class JsonRpcProtocolError(RuntimeError):
    def __init__(
        self,
        code: int,
        message: str,
        *,
        request_id: RequestID | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.data = data


def parse_request(raw: str) -> JsonRpcRequest:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonRpcProtocolError(PARSE_ERROR, "Parse error") from exc

    if not isinstance(message, dict):
        raise JsonRpcProtocolError(INVALID_REQUEST, "Invalid request")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcProtocolError(INVALID_REQUEST, "Invalid request")

    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcProtocolError(INVALID_REQUEST, "Invalid request")

    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise JsonRpcProtocolError(INVALID_PARAMS, "Invalid params")

    has_id = "id" in message
    request_id = message.get("id") if has_id else None
    if has_id and not isinstance(request_id, (int, str)):
        raise JsonRpcProtocolError(INVALID_REQUEST, "Invalid request")

    return JsonRpcRequest(method=method, params=params, request_id=request_id)


def result_message(request_id: RequestID, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def error_message(
    request_id: RequestID | None,
    code: int,
    message: str,
    *,
    data: Any = None,
) -> dict[str, Any]:
    error_obj: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error_obj["data"] = data
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error_obj,
    }


def notification_message(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params,
    }
