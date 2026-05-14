"""Tests for tokenizer abstraction."""

from __future__ import annotations

from taui.agent.tokenizer import Tokenizer, _default_estimator, create_tokenizer


class TestDefaultEstimator:
    def test_basic(self):
        assert _default_estimator("hello") > 0

    def test_empty(self):
        assert _default_estimator("") >= 1

    def test_long_text(self):
        text = "a" * 1000
        tokens = _default_estimator(text)
        assert 200 < tokens < 350  # ~250 for 1000 chars


class TestTokenizer:
    def test_default_estimate(self):
        tok = Tokenizer()
        assert tok.estimate("hello world") > 0

    def test_custom_estimator(self):
        tok = Tokenizer(estimator=lambda text: len(text))
        assert tok.estimate("hello") == 5

    def test_calibration(self):
        tok = Tokenizer()
        text = "hello world " * 20  # long enough to avoid truncation to same int
        initial = tok.estimate(text)
        # Pretend actual was 2x our estimate
        tok.calibrate(initial, initial * 2)
        after = tok.estimate(text)
        assert after > initial  # Should be higher after calibration

    def test_calibration_converges(self):
        tok = Tokenizer()
        # Repeatedly calibrate with 2x actual
        for _ in range(20):
            est = tok.estimate("test text")
            tok.calibrate(est, est * 2)
        # Should converge toward factor of 2
        assert 1.8 < tok.calibration_factor < 2.2

    def test_calibration_zero_safe(self):
        tok = Tokenizer()
        tok.calibrate(0, 100)  # should not crash
        tok.calibrate(100, 0)
        assert tok.calibration_factor == 1.0


class TestCreateTokenizer:
    def test_default(self):
        tok = create_tokenizer()
        assert isinstance(tok, Tokenizer)

    def test_copilot(self):
        tok = create_tokenizer("copilot")
        assert isinstance(tok, Tokenizer)
