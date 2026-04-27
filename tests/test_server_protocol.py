"""Tests for taui.server.protocol module."""

from __future__ import annotations

import pytest

from taui.server.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcProtocolError,
    JsonRpcRequest,
    error_message,
    notification_message,
    parse_request,
    result_message,
)


# ── parse_request ──────────────────────────────────────────────────────────────


class TestParseRequest:
    def test_valid_request(self):
        raw = '{"jsonrpc":"2.0","id":1,"method":"test","params":{"a":1}}'
        req = parse_request(raw)
        assert req.method == "test"
        assert req.params == {"a": 1}
        assert req.request_id == 1
        assert not req.is_notification

    def test_notification(self):
        raw = '{"jsonrpc":"2.0","method":"notify","params":{}}'
        req = parse_request(raw)
        assert req.is_notification
        assert req.request_id is None

    def test_string_id(self):
        raw = '{"jsonrpc":"2.0","id":"abc","method":"m","params":{}}'
        req = parse_request(raw)
        assert req.request_id == "abc"

    def test_missing_params_defaults_empty(self):
        raw = '{"jsonrpc":"2.0","id":1,"method":"m"}'
        req = parse_request(raw)
        assert req.params == {}

    def test_null_params_defaults_empty(self):
        raw = '{"jsonrpc":"2.0","id":1,"method":"m","params":null}'
        req = parse_request(raw)
        assert req.params == {}

    def test_invalid_json(self):
        with pytest.raises(JsonRpcProtocolError) as exc_info:
            parse_request("not json")
        assert exc_info.value.code == PARSE_ERROR

    def test_not_dict(self):
        with pytest.raises(JsonRpcProtocolError) as exc_info:
            parse_request("[1,2,3]")
        assert exc_info.value.code == INVALID_REQUEST

    def test_wrong_version(self):
        with pytest.raises(JsonRpcProtocolError):
            parse_request('{"jsonrpc":"1.0","id":1,"method":"m"}')

    def test_missing_method(self):
        with pytest.raises(JsonRpcProtocolError):
            parse_request('{"jsonrpc":"2.0","id":1}')

    def test_empty_method(self):
        with pytest.raises(JsonRpcProtocolError):
            parse_request('{"jsonrpc":"2.0","id":1,"method":""}')

    def test_non_dict_params(self):
        with pytest.raises(JsonRpcProtocolError) as exc_info:
            parse_request('{"jsonrpc":"2.0","id":1,"method":"m","params":[1]}')
        assert exc_info.value.code == INVALID_PARAMS

    def test_non_int_str_id(self):
        with pytest.raises(JsonRpcProtocolError):
            parse_request('{"jsonrpc":"2.0","id":1.5,"method":"m"}')


# ── message builders ───────────────────────────────────────────────────────────


class TestResultMessage:
    def test_basic(self):
        msg = result_message(1, {"ok": True})
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 1
        assert msg["result"] == {"ok": True}

    def test_null_result(self):
        msg = result_message("abc", None)
        assert msg["result"] is None


class TestErrorMessage:
    def test_basic(self):
        msg = error_message(1, INTERNAL_ERROR, "boom")
        assert msg["error"]["code"] == INTERNAL_ERROR
        assert msg["error"]["message"] == "boom"
        assert "data" not in msg["error"]

    def test_with_data(self):
        msg = error_message(None, METHOD_NOT_FOUND, "nope", data={"detail": "x"})
        assert msg["id"] is None
        assert msg["error"]["data"] == {"detail": "x"}


class TestNotificationMessage:
    def test_basic(self):
        msg = notification_message("event/update", {"key": "val"})
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "event/update"
        assert msg["params"] == {"key": "val"}
        assert "id" not in msg


# ── error class ────────────────────────────────────────────────────────────────


class TestJsonRpcProtocolError:
    def test_attributes(self):
        err = JsonRpcProtocolError(
            INVALID_REQUEST, "bad request", request_id=42, data={"x": 1}
        )
        assert err.code == INVALID_REQUEST
        assert err.message == "bad request"
        assert err.request_id == 42
        assert err.data == {"x": 1}
        assert str(err) == "bad request"


# ── request dataclass ──────────────────────────────────────────────────────────


class TestJsonRpcRequest:
    def test_is_notification_true(self):
        r = JsonRpcRequest(method="m", params={}, request_id=None)
        assert r.is_notification

    def test_is_notification_false(self):
        r = JsonRpcRequest(method="m", params={}, request_id=1)
        assert not r.is_notification
