from __future__ import annotations

import json

import pytest

from taui.server.protocol import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JsonRpcProtocolError,
    error_message,
    parse_request,
    result_message,
)


def test_parse_valid_request_shape() -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "spec/getTree",
        "params": {},
    }
    parsed = parse_request(json.dumps(message))
    assert parsed.request_id == 42
    assert parsed.method == "spec/getTree"
    assert parsed.params == {}


def test_parse_error_for_invalid_json() -> None:
    with pytest.raises(JsonRpcProtocolError) as exc_info:
        parse_request("{not-json")
    assert exc_info.value.code == PARSE_ERROR


def test_invalid_request_for_missing_method() -> None:
    payload = {"jsonrpc": "2.0", "id": 1}
    with pytest.raises(JsonRpcProtocolError) as exc_info:
        parse_request(json.dumps(payload))
    assert exc_info.value.code == INVALID_REQUEST


def test_result_and_error_message_shapes() -> None:
    result = result_message(7, {"ok": True})
    assert result == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}

    error = error_message(7, -32600, "Invalid request")
    assert error["jsonrpc"] == "2.0"
    assert error["id"] == 7
    assert error["error"]["code"] == -32600
    assert error["error"]["message"] == "Invalid request"

