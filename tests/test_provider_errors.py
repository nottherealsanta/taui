"""Tests for typed provider error taxonomy."""

from __future__ import annotations

from taui.llm_provider.errors import (
    AuthExpiredError,
    ContextOverflowError,
    ProviderError,
    QuotaExceededError,
    TransientProviderError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_provider_error(self):
        for cls in (
            ContextOverflowError, QuotaExceededError,
            TransientProviderError, AuthExpiredError,
        ):
            assert issubclass(cls, ProviderError)
            assert issubclass(cls, Exception)

    def test_context_overflow_attributes(self):
        err = ContextOverflowError("too long", status_code=400, body='{"error":"..."}')
        assert str(err) == "too long"
        assert err.status_code == 400
        assert err.body == '{"error":"..."}'

    def test_quota_exceeded_with_reset(self):
        err = QuotaExceededError("limit reached", resets_in_seconds=3600)
        assert err.resets_in_seconds == 3600
        assert str(err) == "limit reached"

    def test_quota_exceeded_without_reset(self):
        err = QuotaExceededError("limit reached")
        assert err.resets_in_seconds is None

    def test_transient_with_retry_after(self):
        err = TransientProviderError("rate limited", retry_after=5.0)
        assert err.retry_after == 5.0

    def test_transient_without_retry_after(self):
        err = TransientProviderError("server error")
        assert err.retry_after is None

    def test_auth_expired(self):
        err = AuthExpiredError("token expired")
        assert isinstance(err, ProviderError)
        assert str(err) == "token expired"

    def test_provider_error_base_attributes(self):
        err = ProviderError("base error", status_code=500, body="internal error")
        assert err.status_code == 500
        assert err.body == "internal error"

    def test_provider_error_defaults(self):
        err = ProviderError("simple error")
        assert err.status_code is None
        assert err.body == ""


class TestErrorClassification:
    """Test that base.py error classification methods still work."""

    def _make_provider(self):
        from taui.llm_provider.base import BaseLLMProvider
        from taui.llm_provider.types import LLMRequest, ProviderCapabilities, StreamEvent

        class MockProvider(BaseLLMProvider):
            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(supports_tools=True, supports_streaming=True)

            def build_request(self, messages, model, temperature, **kwargs) -> LLMRequest:
                return LLMRequest(url="http://test", headers={}, body={})

            def parse_stream_event(self, data: str) -> StreamEvent | None:
                return None

            def refresh_credentials(self) -> None:
                pass

        return MockProvider()

    def test_is_context_overflow_matches_patterns(self):
        p = self._make_provider()
        assert p.is_context_overflow(400, "prompt is too long for this model")
        assert p.is_context_overflow(400, "exceeds the context window")
        assert p.is_context_overflow(400, "maximum context length is 4096 tokens")
        assert not p.is_context_overflow(400, "some unrelated error")

    def test_is_usage_limit_requires_429(self):
        p = self._make_provider()
        assert p.is_usage_limit(429, "usage_limit_reached")
        assert p.is_usage_limit(429, "quota_exceeded for your plan")
        assert not p.is_usage_limit(400, "usage_limit_reached")  # non-429 status
        assert not p.is_usage_limit(429, "rate limited temporarily")

    def test_is_retryable_status_codes(self):
        p = self._make_provider()
        for status in (429, 500, 502, 503, 504):
            assert p.is_retryable(status, "")
        assert not p.is_retryable(400, "bad request")
        assert not p.is_retryable(404, "not found")

    def test_is_retryable_patterns(self):
        p = self._make_provider()
        assert p.is_retryable(400, "rate limit exceeded")
        assert p.is_retryable(400, "service unavailable due to overload")
