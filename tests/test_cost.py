"""Tests for taui.cost."""

from taui.cost import CostTracker, estimate_cost


class TestEstimateCost:
    def test_known_model(self):
        cost = estimate_cost("claude-sonnet-4.6", 1_000_000, 1_000_000)
        assert cost == 3.00 + 15.00  # 18.00

    def test_unknown_model_uses_default(self):
        cost = estimate_cost("unknown-model", 1_000_000, 0)
        assert cost == 3.00  # default input rate

    def test_prefix_match(self):
        cost = estimate_cost("claude-sonnet-4-20250514-preview", 1_000_000, 0)
        assert cost == 3.00

    def test_zero_tokens(self):
        assert estimate_cost("claude-sonnet-4.6", 0, 0) == 0.0


class TestCostTracker:
    def test_record(self):
        t = CostTracker()
        rec = t.record(model="claude-sonnet-4.6", input_tokens=1000, output_tokens=500)
        assert rec.input_tokens == 1000
        assert rec.output_tokens == 500
        assert rec.cost_usd > 0

    def test_accumulates(self):
        t = CostTracker()
        t.record(model="test", input_tokens=100, output_tokens=50)
        t.record(model="test", input_tokens=200, output_tokens=100)
        assert t.total_input_tokens == 300
        assert t.total_output_tokens == 150
        assert t.turn_count == 2

    def test_summary(self):
        t = CostTracker()
        t.record(model="test", input_tokens=1000, output_tokens=500)
        s = t.summary()
        assert "1,000in" in s
        assert "500out" in s
        assert "$" in s
        assert "turns: 1" in s

    def test_to_dict(self):
        t = CostTracker()
        t.record(model="test", input_tokens=100, output_tokens=50)
        d = t.to_dict()
        assert d["total_input_tokens"] == 100
        assert d["total_output_tokens"] == 50
        assert d["turn_count"] == 1

    def test_explicit_cost(self):
        t = CostTracker()
        t.record(model="test", input_tokens=100, output_tokens=50, cost_usd=0.42)
        assert t.total_cost_usd == 0.42
