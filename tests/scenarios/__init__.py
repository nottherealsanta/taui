"""Provider scenario harness for testing taui against scripted LLM behavior.

This package is consumed by:
- unit/integration tests in `tests/`
- visual snapshot tests in `tests/test_tui_visual.py`
- coding agents that need to exercise taui without hitting a real provider

The two pieces are:

- `ScriptedProvider` — duck-types the LLM provider contract used by `AgentLoop`
  (`create_turn` + `on_text_delta` / `on_reasoning_delta` callbacks).
- `scenarios.*` — named factories that return preconfigured `ScriptedProvider`
  instances for common situations (happy path, tool calls, rate limit, etc.).

Typical use::

    from tests.scenarios import ScriptedProvider, Turn, scenarios

    provider = scenarios.happy_path("Hello there!")
    # ...or build one by hand:
    provider = ScriptedProvider([
        Turn(text_deltas=["Hi ", "there!"], text="Hi there!"),
    ])
"""

from .scripted_provider import (
    ScriptedProvider,
    ScriptedToolCall,
    Turn,
    raises,
)

__all__ = [
    "ScriptedProvider",
    "ScriptedToolCall",
    "Turn",
    "raises",
    "scenarios",
]

from . import scenarios  # noqa: E402  (kept after __all__ for IDE friendliness)
