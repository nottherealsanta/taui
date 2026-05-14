"""Tests for RunResult.total_usage and cost_usd."""

from taui.agent.loop import AgentState, RunResult, TurnResult


class TestRunResultUsage:
    def test_total_usage_aggregates(self):
        result = RunResult(
            text="done",
            turns=2,
            turn_results=[
                TurnResult(
                    text="a",
                    tool_calls_count=0,
                    turn_number=0,
                    usage={"input_tokens": 100, "output_tokens": 50},
                ),
                TurnResult(
                    text="b",
                    tool_calls_count=0,
                    turn_number=1,
                    usage={"input_tokens": 200, "output_tokens": 100},
                ),
            ],
        )
        usage = result.total_usage
        assert usage["input_tokens"] == 300
        assert usage["output_tokens"] == 150

    def test_total_usage_no_usage_data(self):
        result = RunResult(
            text="done",
            turns=1,
            turn_results=[
                TurnResult(text="a", tool_calls_count=0, turn_number=0),
            ],
        )
        usage = result.total_usage
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0

    def test_cost_usd_with_per_turn_costs(self):
        result = RunResult(
            text="done",
            turns=2,
            turn_results=[
                TurnResult(
                    text="a",
                    tool_calls_count=0,
                    turn_number=0,
                    usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
                ),
                TurnResult(
                    text="b",
                    tool_calls_count=0,
                    turn_number=1,
                    usage={"input_tokens": 200, "output_tokens": 100, "cost_usd": 0.002},
                ),
            ],
        )
        assert result.cost_usd == 0.003

    def test_cost_usd_none_when_no_usage(self):
        result = RunResult(
            text="done",
            turns=1,
            turn_results=[
                TurnResult(text="a", tool_calls_count=0, turn_number=0),
            ],
        )
        assert result.cost_usd is None

    def test_total_usage_with_cache_tokens(self):
        result = RunResult(
            text="done",
            turns=1,
            turn_results=[
                TurnResult(
                    text="a",
                    tool_calls_count=0,
                    turn_number=0,
                    usage={
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_tokens": 30,
                        "cache_write_tokens": 10,
                    },
                ),
            ],
        )
        usage = result.total_usage
        assert usage["cache_read_tokens"] == 30
        assert usage["cache_write_tokens"] == 10

    def test_cost_usd_none_when_tokens_but_no_cost_usd_key(self):
        """When usage has tokens but no cost_usd key, cost_usd returns None."""
        result = RunResult(
            text="done",
            turns=1,
            turn_results=[
                TurnResult(
                    text="a",
                    tool_calls_count=0,
                    turn_number=0,
                    usage={"input_tokens": 100, "output_tokens": 50},
                ),
            ],
        )
        assert result.cost_usd is None

    def test_state_default(self):
        result = RunResult(text="done", turns=1)
        assert result.state == AgentState.DONE
