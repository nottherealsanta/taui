"""Question tool — ask the user for clarification."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class QuestionTool:
    """Ask the user a question and wait for a response.

    The tool blocks until the user responds. Uses a callback (set by the CLI
    or other frontend) to deliver the question and receive the answer.
    """

    name: str = "question"
    description: str = (
        "Ask the user a question when you need clarification or a decision. "
        "Provide 2–3 suggested answers as options. "
        "Suffix an option with ' (Recommended)' if you have a preferred choice."
    )
    category: ToolCategory = ToolCategory.QUESTION
    guidelines: str = (
        "Use `question` when you need user input to proceed. "
        "Don't ask unnecessary questions — only when genuinely uncertain. "
        "Always provide 2–3 concise options. Mark your recommended option "
        "with ' (Recommended)' at the end of the string."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Callback: async (question, options) -> answer_str | None
    _ask: Any = None

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "2–3 suggested answers. Append ' (Recommended)' "
                            "to your preferred choice. The user can always "
                            "type a custom answer instead."
                        ),
                    },
                },
                "required": ["question"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return ToolResult.fail("'question' must be a non-empty string.")

        options = arguments.get("options")
        if options is not None and not isinstance(options, list):
            options = None

        if self._ask is None:
            return ToolResult.ok(
                "No interactive mechanism available. Proceed with your best judgment.",
                answered=False,
            )

        try:
            answer = await self._ask(question, options)
        except Exception as exc:
            return ToolResult.fail(f"Failed to get answer: {exc}")

        if answer is None:
            return ToolResult.ok(
                "Question was dismissed. Proceed with your best judgment.",
                answered=False,
            )

        return ToolResult.ok(f"User answered: {answer}", answered=True, answer=answer)
