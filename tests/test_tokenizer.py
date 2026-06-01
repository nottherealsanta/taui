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

    def test_estimate_chars(self):
        """A3: estimate_chars converts a character count to tokens without allocating a string."""
        tok = Tokenizer()
        char_count = 1000
        result = tok.estimate_chars(char_count)
        # Should be approximately char_count // 4 + 1 (with calibration factor 1.0)
        assert result == max(1, int((char_count // 4 + 1) * 1.0))

    def test_estimate_chars_respects_calibration(self):
        """estimate_chars must apply the calibration factor."""
        tok = Tokenizer()
        # Calibrate to factor ~2.0
        for _ in range(20):
            est = tok.estimate("test text")
            tok.calibrate(est, est * 2)

        result = tok.estimate_chars(1000)
        # With factor ~2.0, result should be roughly 2 * (1000//4+1) ≈ 502
        assert result > 400

    def test_estimate_chars_vs_estimate_consistency(self):
        """estimate_chars(len(text)) should be close to estimate(text) for default estimator."""
        tok = Tokenizer()
        text = "Hello world, this is a test sentence with some words."
        est_text = tok.estimate(text)
        est_chars = tok.estimate_chars(len(text))
        assert est_text == est_chars


class TestCreateTokenizer:
    def test_default(self):
        tok = create_tokenizer()
        assert isinstance(tok, Tokenizer)

    def test_copilot(self):
        tok = create_tokenizer("copilot")
        assert isinstance(tok, Tokenizer)
