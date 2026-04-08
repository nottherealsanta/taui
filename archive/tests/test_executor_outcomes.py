from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from taui.agent.session import Session
from taui.config.policies import Policy
from taui.config.settings import Settings
from taui.tools.base import Tool, ToolContext, ToolResult
from taui.tools.executor import (
    ExecutionCompleted,
    ExecutionDenied,
    ExecutionRequiresApproval,
    ToolExecutor,
)
from taui.tools.registry import ToolRegistry


@dataclass(slots=True)
class DummyTool(Tool):
    name: str = "dummy"
    description: str = "dummy tool"
    schema: dict[str, object] | None = None
    origin: str = "builtin"

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        del context
        return ToolResult.ok(str(arguments["value"]))


def _context(workspace: Path, settings: Settings) -> ToolContext:
    return ToolContext(
        working_dir=workspace,
        session=Session(),
        policy=Policy.from_settings(settings),
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(DummyTool())
    return registry


def test_confirm_required_outcome(tmp_path: Path) -> None:
    settings = Settings()
    settings.policy.auto_approve = ()
    settings.policy.confirm = ()
    settings.policy.deny = ()

    outcome = asyncio.run(
        ToolExecutor(_registry()).run(
            tool_call_id="t1",
            tool_name="dummy",
            arguments={"value": "x"},
            context=_context(tmp_path, settings),
        )
    )

    assert isinstance(outcome, ExecutionRequiresApproval)


def test_approved_execution_completes(tmp_path: Path) -> None:
    settings = Settings()
    settings.policy.auto_approve = ("dummy",)

    outcome = asyncio.run(
        ToolExecutor(_registry()).run(
            tool_call_id="t2",
            tool_name="dummy",
            arguments={"value": "ok"},
            context=_context(tmp_path, settings),
        )
    )

    assert isinstance(outcome, ExecutionCompleted)
    assert outcome.result.error is False
    assert outcome.result.content == "ok"


def test_denied_after_prompt(tmp_path: Path) -> None:
    settings = Settings()
    settings.policy.confirm = ("dummy",)
    settings.policy.auto_approve = ()

    outcome = asyncio.run(
        ToolExecutor(_registry()).run(
            tool_call_id="t3",
            tool_name="dummy",
            arguments={"value": "no"},
            context=_context(tmp_path, settings),
            approved=False,
        )
    )

    assert isinstance(outcome, ExecutionDenied)
