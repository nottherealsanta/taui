"""
taui.server — FastAPI + WebSocket web server.

Provides a JSON-RPC 2.0 WebSocket interface to the agent session.
Opt-in via ``taui --web``. Requires fastapi + uvicorn.
"""

from taui.server.protocol import (
    JsonRpcProtocolError,
    JsonRpcRequest,
    error_message,
    notification_message,
    parse_request,
    result_message,
)

__all__ = [
    "JsonRpcProtocolError",
    "JsonRpcRequest",
    "error_message",
    "notification_message",
    "parse_request",
    "result_message",
]
