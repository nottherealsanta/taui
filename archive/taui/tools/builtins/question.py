"""Question tool — ask the user structured questions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error


@dataclass(slots=True)
class QuestionTool:
    """Ask the user a question and wait for a response."""

    name: str = "question"
    description: str = (
        "Ask the user a question when you need clarification or a decision. "
        "Provide the question text and optional answer choices. The tool blocks "
        "until the user responds."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.PLAN

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of answer choices",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context for why this question is being asked",
                    },
                },
                "required": ["question"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return normalize_tool_error(
                "Invalid question arguments: 'question' must be a non-empty string."
            )

        options = arguments.get("options")
        question_context = arguments.get("context", "")

        # Try to route through the agent runner's ask_question
        runner = getattr(context.session, "agent_runner", None)
        if runner is not None and hasattr(runner, "ask_question"):
            spec_ref = getattr(runner, "spec_ref", "")
            answer = await runner.ask_question(
                spec_ref=spec_ref,
                question=question,
                options=options if isinstance(options, list) else None,
            )
            if answer is None:
                return ToolResult.ok(
                    "Question was dismissed or timed out. Proceed with your best judgment.",
                    metadata={"answered": False, "question": question},
                )
            return ToolResult.ok(
                f"User answered: {answer}",
                metadata={"answered": True, "answer": answer, "question": question},
            )

        # No runner available — return a notice
        return ToolResult.ok(
            "Question submitted. No interactive answer mechanism available; "
            "proceed with your best judgment.",
            metadata={"answered": False, "question": question},
        )
